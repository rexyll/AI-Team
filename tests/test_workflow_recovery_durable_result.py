from datetime import datetime, timedelta, timezone

import pytest

from runtime.task import Task
from runtime.task_lease import TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_manager import TaskManager
from runtime.task_result_store import DurableTaskResultStore
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery_runner import WorkflowRecoveryRunError, WorkflowRecoveryRunner

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


class _DurableWorkflow:
    def __init__(self, task_manager, *, delivery_key="recovery-delivery-1"):
        self.task_manager = task_manager
        self.delivery_key = delivery_key
        self.calls = 0

    def execute(self, task_id):
        self.calls += 1
        self.task_manager.commit_task_result(
            task_id,
            self.delivery_key,
            {"ok": True, "attempt": self.calls},
        )
        return self.task_manager.get_task(task_id)


def _assessment():
    return StuckTaskAssessment(
        "TASK-DURABLE-RECOVERY",
        "old-worker",
        TaskLivenessState.STUCK,
        timedelta(seconds=61),
        timedelta(seconds=121),
    )


def _checkpoint_and_leases(result_store):
    task = Task(
        "TASK-DURABLE-RECOVERY",
        "durable recovery",
        "recover durable result",
        "developer",
        status="running",
    )
    manager = TaskManager([task], result_store=result_store)
    leases = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    leases.acquire(task.id, "old-worker", now=NOW)
    return task, manager, leases, WorkflowCheckpoint.capture(task)


def test_recovery_commit_is_durable_and_restart_reconciles_without_reexecution(tmp_path):
    result_store = DurableTaskResultStore(tmp_path)
    task, manager, leases, checkpoint = _checkpoint_and_leases(result_store)
    workflow = _DurableWorkflow(manager)

    first = WorkflowRecoveryRunner(workflow, leases).restart(
        checkpoint,
        _assessment(),
        owner_id="new-worker",
        now=NOW + timedelta(seconds=31),
    )

    assert workflow.calls == 1
    assert first.task.status == "completed"
    durable = result_store.get(task.id)
    assert durable is not None
    assert durable.delivery_key == "recovery-delivery-1"
    assert durable.result == {"attempt": 1, "ok": True}

    restored_manager = TaskManager(
        [Task(task.id, task.title, task.description, task.role, status="running")],
        result_store=DurableTaskResultStore(tmp_path),
    )
    restored = restored_manager.reconcile_durable_result(task.id)

    assert restored.status == "completed"
    assert restored.result == {"attempt": 1, "ok": True}


def test_duplicate_recovery_result_commit_does_not_overwrite_first_result(tmp_path):
    result_store = DurableTaskResultStore(tmp_path)
    task = Task("TASK-DUP-RECOVERY", "duplicate", "recovery", "developer", status="running")
    manager = TaskManager([task], result_store=result_store)

    first = manager.commit_task_result(task.id, "delivery-1", {"value": 1})
    second = manager.commit_task_result(task.id, "delivery-1", {"value": 999})

    assert first.result == {"value": 1}
    assert second.result == {"value": 1}
    assert result_store.get(task.id).result == {"value": 1}


def test_different_recovery_delivery_cannot_replace_authoritative_result(tmp_path):
    result_store = DurableTaskResultStore(tmp_path)
    task = Task("TASK-DIFF-RECOVERY", "different", "recovery", "developer", status="running")
    manager = TaskManager([task], result_store=result_store)
    manager.commit_task_result(task.id, "delivery-1", {"value": 1})

    with pytest.raises(ValueError, match="already has a committed result"):
        manager.commit_task_result(task.id, "delivery-2", {"value": 2})

    assert result_store.get(task.id).result == {"value": 1}
