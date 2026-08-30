import pytest

from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.workflow_checkpoint import WorkflowCheckpoint, WorkflowCheckpointError


def test_checkpoint_captures_and_restores_without_aliasing():
    task = Task("TASK-CP", "checkpoint", "state", "developer")
    task.status = TaskStatus.REVIEW_PENDING.value
    task.status_history.append({"from": "pending", "to": "ready"})
    task.context["checkpoint"] = "v1"

    checkpoint = WorkflowCheckpoint.capture(task)
    task.context["checkpoint"] = "mutated"

    restored = checkpoint.restore()
    assert restored.id == task.id
    assert restored.status == TaskStatus.REVIEW_PENDING.value
    assert restored.status_history == [{"from": "pending", "to": "ready"}]
    assert restored.context["checkpoint"] == "v1"


def test_checkpoint_round_trip_is_versioned_and_deterministic():
    task = Task("TASK-CP", "checkpoint", "state", "developer")
    checkpoint = WorkflowCheckpoint.capture(task)
    payload = checkpoint.to_dict()
    restored = WorkflowCheckpoint.from_dict(payload)
    assert restored.to_dict() == payload


def test_checkpoint_rejects_mismatched_or_unsupported_payloads():
    with pytest.raises(WorkflowCheckpointError):
        WorkflowCheckpoint.from_dict({"version": 1, "task_id": "A", "task": {"id": "B"}})
    with pytest.raises(WorkflowCheckpointError):
        WorkflowCheckpoint.from_dict({"version": 2, "task_id": "A", "task": {"id": "A"}})
    with pytest.raises(WorkflowCheckpointError):
        WorkflowCheckpoint.from_dict({"version": 1, "task_id": "A", "task": None})
