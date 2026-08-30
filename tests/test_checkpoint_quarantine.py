from runtime.checkpoint_quarantine import CheckpointQuarantine
from runtime.task import Task
from runtime.task_status import TaskStatus


def _snapshot(task_id: str, status: str = TaskStatus.READY.value) -> dict:
    return Task(task_id, task_id, "recover", "developer").to_dict() | {"status": status}


def test_invalid_checkpoint_is_quarantined_without_blocking_valid_tasks():
    result = CheckpointQuarantine().recover([
        _snapshot("TASK-VALID"),
        {"id": "TASK-BAD", "title": "bad", "description": "recover", "role": "developer", "status": "corrupt"},
    ])
    assert [task.id for task in result.tasks] == ["TASK-VALID"]
    assert [item.task_id for item in result.quarantined] == ["TASK-BAD"]
    assert result.quarantined[0].reason == "invalid task status"


def test_duplicate_checkpoint_is_quarantined():
    snapshot = _snapshot("TASK-DUP")
    result = CheckpointQuarantine().recover([snapshot, snapshot])
    assert [task.id for task in result.tasks] == ["TASK-DUP"]
    assert result.quarantined[0].reason == "duplicate checkpoint id"


def test_quarantine_keeps_original_snapshot_isolated():
    snapshot = _snapshot("TASK-ISO")
    result = CheckpointQuarantine().recover([snapshot])
    snapshot["title"] = "mutated"
    assert result.tasks[0].title == "TASK-ISO"
