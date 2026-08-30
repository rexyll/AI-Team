from datetime import datetime, timedelta, timezone

import pytest

from runtime.persistent_task_manager import PersistentTaskManager
from runtime.task import Task
from runtime.task_lease import LeaseOwnershipError, TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.task_status import TaskStatus
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery import WorkflowRecovery
from runtime.workflow_recovery_runner import WorkflowRecoveryRunner
from runtime.workflow_resume import WorkflowResumePlanner


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _manager(store):
    tasks = [
        Task("TASK-DONE", "done", "completed work", "developer"),
        Task("TASK-RESUME", "resume", "unfinished work", "developer"),
    ]
    tasks[0].status = TaskStatus.COMPLETED.value
    tasks[0].status_history.append({"from": TaskStatus.RUNNING.value, "to": TaskStatus.COMPLETED.value})
    tasks[1].status = TaskStatus.READY.value
    return PersistentTaskManager(tasks, state_store=store)


def test_crash_restart_recovers_completed_and_resumable_state_without_replaying_completion():
    store = InMemoryTaskStateStore()
    manager = _manager(store)
    before = store.snapshot()

    checkpoints = [
        WorkflowCheckpoint.capture(manager.get_task("TASK-DONE")),
        WorkflowCheckpoint.capture(manager.get_task("TASK-RESUME")),
    ]
    recovered_tasks = WorkflowRecovery().recover_tasks(checkpoints).tasks

    # WorkflowExecutionState exposes an immutable tuple; TaskManager intentionally
    # requires a concrete list of tasks at construction time.
    restarted = PersistentTaskManager(list(recovered_tasks), state_store=store, persist_initial=False)
    plan = WorkflowResumePlanner().plan(list(restarted.tasks.values()))

    assert plan.resumable_task_ids == ("TASK-RESUME",)
    assert restarted.get_task("TASK-DONE").status == TaskStatus.COMPLETED.value
    assert restarted.get_task("TASK-DONE").status_history == [
        {"from": TaskStatus.RUNNING.value, "to": TaskStatus.COMPLETED.value}
    ]
    assert store.snapshot() == before


def test_crash_restart_fences_old_worker_after_recovery_takeover():
    task = Task("TASK-FENCE-RESTART", "resume", "unfinished work", "developer", status=TaskStatus.RUNNING.value)
    store = InMemoryTaskStateStore()
    task_manager = PersistentTaskManager([task], state_store=store)
    checkpoint = WorkflowCheckpoint.capture(task)

    leases = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    old_lease = leases.acquire(task.id, "worker-a", now=NOW)

    assessment = StuckTaskAssessment(
        task.id,
        "worker-a",
        TaskLivenessState.STUCK,
        timedelta(seconds=31),
        timedelta(seconds=61),
    )

    class Workflow:
        def __init__(self):
            self.task_manager = task_manager
            self.calls = 0

        def execute(self, task_id):
            self.calls += 1
            return self.task_manager.get_task(task_id)

    workflow = Workflow()
    result = WorkflowRecoveryRunner(workflow, leases).restart(
        checkpoint,
        assessment,
        owner_id="worker-b",
        now=NOW + timedelta(seconds=31),
    )

    assert result.takeover.lease.generation == old_lease.generation + 1
    assert workflow.calls == 1
    with pytest.raises(LeaseOwnershipError):
        leases.assert_current(
            task.id,
            old_lease.lease.owner_id,
            old_lease.lease.token,
            old_lease.generation,
            now=NOW + timedelta(seconds=31),
        )
    assert leases.get(task.id, now=NOW + timedelta(seconds=31)) is None
