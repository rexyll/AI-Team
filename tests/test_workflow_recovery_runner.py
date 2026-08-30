from datetime import datetime, timedelta, timezone

import pytest

from runtime.task import Task
from runtime.task_lease import TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_manager import TaskManager
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery_runner import WorkflowRecoveryRunError, WorkflowRecoveryRunner

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


class _Workflow:
    def __init__(self, task_manager, *, fail=False):
        self.task_manager = task_manager
        self.calls = []
        self.fail = fail

    def execute(self, task_id):
        self.calls.append(task_id)
        if self.fail:
            raise RuntimeError("boom")
        return self.task_manager.get_task(task_id)


def _task():
    return Task("TASK-RESTART", "restart", "unfinished", "developer", status="running")


def _assessment():
    return StuckTaskAssessment(
        "TASK-RESTART",
        "old-worker",
        TaskLivenessState.STUCK,
        timedelta(seconds=61),
        timedelta(seconds=121),
    )


def _setup(*, fail=False):
    task = _task()
    manager = TaskManager([task])
    workflow = _Workflow(manager, fail=fail)
    leases = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    leases.acquire("TASK-RESTART", "old-worker", now=NOW)
    checkpoint = WorkflowCheckpoint.capture(task)
    return task, manager, workflow, leases, checkpoint


def test_restart_executes_recovered_task_once_and_releases_takeover_lease():
    task, _, workflow, leases, checkpoint = _setup()
    result = WorkflowRecoveryRunner(workflow, leases).restart(
        checkpoint, _assessment(), owner_id="new-worker", now=NOW + timedelta(seconds=31)
    )
    assert result.task.id == task.id
    assert workflow.calls == [task.id]
    assert leases.get(task.id, now=NOW + timedelta(seconds=31)) is None


def test_restart_releases_takeover_lease_when_workflow_fails():
    _, _, workflow, leases, checkpoint = _setup(fail=True)
    with pytest.raises(WorkflowRecoveryRunError):
        WorkflowRecoveryRunner(workflow, leases).restart(
            checkpoint, _assessment(), owner_id="new-worker", now=NOW + timedelta(seconds=31)
        )
    assert workflow.calls == [checkpoint.task_id]
    assert leases.get(checkpoint.task_id, now=NOW + timedelta(seconds=31)) is None


def test_restart_rejects_terminal_task_before_execution():
    task, manager, workflow, leases, checkpoint = _setup()
    manager.get_task(task.id).status = "completed"
    with pytest.raises(WorkflowRecoveryRunError):
        WorkflowRecoveryRunner(workflow, leases).restart(
            checkpoint, _assessment(), owner_id="new-worker", now=NOW + timedelta(seconds=31)
        )
    assert workflow.calls == []
    assert leases.get(task.id, now=NOW + timedelta(seconds=31)) is None
