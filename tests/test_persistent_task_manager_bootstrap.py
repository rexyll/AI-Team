import pytest

from runtime.persistent_task_manager import PersistentTaskManager
from runtime.task import Task
from runtime.task_recovery import TaskRecoveryError
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.task_status import TaskStatus


def _persisted_store():
    task = Task("TASK-BOOT", "boot", "recover me", "developer")
    task.status = TaskStatus.REVIEW_PENDING.value
    task.status_history.append({"from": TaskStatus.PENDING.value, "to": TaskStatus.READY.value})
    store = InMemoryTaskStateStore()
    store.save(task)
    return store


def test_bootstrap_loads_persisted_task_state():
    store = _persisted_store()
    manager = PersistentTaskManager.from_state_store(store)
    task = manager.get_task("TASK-BOOT")
    assert task.status == TaskStatus.REVIEW_PENDING.value
    assert task.status_history == [{"from": "pending", "to": "ready"}]


def test_bootstrap_can_continue_lifecycle_after_recovery():
    store = _persisted_store()
    manager = PersistentTaskManager.from_state_store(store)
    manager.transition("TASK-BOOT", TaskStatus.REVIEWING)
    saved = store.load("TASK-BOOT")
    assert saved["status"] == TaskStatus.REVIEWING.value
    assert saved["status_history"][-1] == {"from": "review_pending", "to": "reviewing"}


def test_bootstrap_rejects_invalid_persisted_state():
    store = InMemoryTaskStateStore()
    store._states["BROKEN"] = {"id": "BROKEN"}
    with pytest.raises(TaskRecoveryError):
        PersistentTaskManager.from_state_store(store)
