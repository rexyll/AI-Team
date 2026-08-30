import pytest

from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery import WorkflowRecovery, WorkflowRecoveryError


def _checkpoint(task_id: str, status: str) -> WorkflowCheckpoint:
    task = Task(task_id, task_id, "recovery", "developer")
    task.status = status
    return WorkflowCheckpoint.capture(task)


def test_recovery_classifies_completed_and_resumable_tasks():
    recovery = WorkflowRecovery()
    state = recovery.recover_tasks([
        _checkpoint("TASK-DONE", TaskStatus.COMPLETED.value),
        _checkpoint("TASK-READY", TaskStatus.READY.value),
        _checkpoint("TASK-RUNNING", TaskStatus.RUNNING.value),
    ])
    assert state.completed_task_ids == {"TASK-DONE"}
    assert state.resumable_task_ids == {"TASK-READY", "TASK-RUNNING"}
    assert not state.can_resume("TASK-DONE")
    assert state.can_resume("TASK-READY")


def test_recovery_rejects_duplicate_task_ids():
    recovery = WorkflowRecovery()
    checkpoint = _checkpoint("TASK-DUP", TaskStatus.READY.value)
    with pytest.raises(WorkflowRecoveryError):
        recovery.recover_tasks([checkpoint, checkpoint])


def test_recovery_rejects_non_checkpoint_values():
    with pytest.raises(WorkflowRecoveryError):
        WorkflowRecovery().recover_tasks([object()])
