import pytest

from runtime.persistent_task_manager import PersistentTaskManager
from runtime.task import Task
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.task_status import TaskStatus


class FailingStore(InMemoryTaskStateStore):
    def save(self, task):
        raise OSError("store unavailable")


def test_lifecycle_transition_is_persisted():
    task = Task("TASK-PERSIST", "persist", "state", "developer")
    store = InMemoryTaskStateStore()
    manager = PersistentTaskManager([task], state_store=store)
    manager.transition(task.id, TaskStatus.READY)
    saved = store.load(task.id)
    assert saved["status"] == TaskStatus.READY.value
    assert saved["status_history"][-1]["to"] == TaskStatus.READY.value


def test_initial_state_is_persisted():
    task = Task("TASK-INIT", "init", "state", "developer")
    store = InMemoryTaskStateStore()
    PersistentTaskManager([task], state_store=store)
    assert store.load(task.id)["status"] == TaskStatus.PENDING.value


def test_failed_persistence_rolls_back_in_memory_transition():
    task = Task("TASK-ROLLBACK", "rollback", "state", "developer")
    manager = PersistentTaskManager.__new__(PersistentTaskManager)
    # Construct without initial persistence so the failing store can exercise the transition boundary.
    manager.tasks = {task.id: task}
    manager.state_store = FailingStore()
    manager.result_store = None
    manager._lock = __import__("threading").RLock()
    with pytest.raises(OSError):
        manager.transition(task.id, TaskStatus.READY)
    assert task.status == TaskStatus.PENDING.value
    assert task.status_history == []
