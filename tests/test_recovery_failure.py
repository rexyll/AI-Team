import pytest

from runtime.recovery_failure import RecoveryFailureIsolation
from runtime.task import Task


def _snapshot(task_id: str) -> dict:
    return Task(task_id, task_id, "recover", "developer").to_dict()


def test_unexpected_recovery_failure_isolated_from_other_tasks():
    snapshots = [_snapshot("TASK-1"), _snapshot("TASK-BAD"), _snapshot("TASK-3")]

    def recover_one(snapshot):
        if snapshot["id"] == "TASK-BAD":
            raise RuntimeError("decoder failure")
        return Task.from_dict(snapshot)

    result = RecoveryFailureIsolation().recover(snapshots, recover_one=recover_one)

    assert [task.id for task in result.tasks] == ["TASK-1", "TASK-3"]
    assert [failure.task_id for failure in result.failures] == ["TASK-BAD"]
    assert "RuntimeError" in result.failures[0].reason


def test_recovery_failure_does_not_mutate_input_snapshot():
    snapshot = _snapshot("TASK-BAD")
    original = snapshot.copy()

    def recover_one(value):
        value["title"] = "mutated"
        raise ValueError("bad state")

    result = RecoveryFailureIsolation().recover([snapshot], recover_one=recover_one)
    assert snapshot == original
    assert result.failures[0].snapshot == original


def test_duplicate_ids_are_isolated_without_invoking_recovery():
    snapshot = _snapshot("TASK-DUP")
    calls = []

    def recover_one(value):
        calls.append(value["id"])
        return Task.from_dict(value)

    result = RecoveryFailureIsolation().recover([snapshot, snapshot], recover_one=recover_one)
    assert calls == ["TASK-DUP"]
    assert [item.task_id for item in result.failures] == ["TASK-DUP"]
