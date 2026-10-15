import pytest

from runtime.task import Task
from runtime.task_recovery import TaskRecovery, TaskRecoveryError
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.task_status import TaskStatus


def _store():
    task = Task("TASK-RECOVER", "recover", "state", "developer")
    task.status = TaskStatus.REVIEW_PENDING.value
    task.status_history.append({"from": TaskStatus.PENDING.value, "to": TaskStatus.READY.value})
    task.context["checkpoint"] = "v1"
    store = InMemoryTaskStateStore()
    store.save(task)
    return store, task


def test_recover_restores_persisted_state_without_aliasing():
    store, original = _store()
    recovered = TaskRecovery(store).recover(original.id)
    assert recovered is not original
    assert recovered.status == TaskStatus.REVIEW_PENDING.value
    assert recovered.status_history == original.status_history
    assert recovered.context == {"checkpoint": "v1"}
    recovered.context["checkpoint"] = "v2"
    assert store.load(original.id)["context"]["checkpoint"] == "v1"


def test_recover_does_not_create_new_lifecycle_transition():
    store, original = _store()
    recovered = TaskRecovery(store).recover(original.id)
    assert recovered.status_history == original.status_history


def test_missing_or_invalid_snapshot_is_rejected():
    store = InMemoryTaskStateStore()
    with pytest.raises(TaskRecoveryError):
        TaskRecovery(store).recover("MISSING")
    store._states["BROKEN"] = {"id": "BROKEN"}
    with pytest.raises(TaskRecoveryError):
        TaskRecovery(store).recover("BROKEN")
