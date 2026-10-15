import pytest

from runtime.interrupted_write import InterruptedWriteError, InterruptedWriteTaskStateStore
from runtime.task import Task


def _task(task_id: str, title: str | None = None) -> Task:
    return Task(task_id, title or task_id, "checkpoint", "developer")


def test_interrupted_batch_write_preserves_last_committed_snapshot():
    store = InterruptedWriteTaskStateStore()
    store.save_many([_task("TASK-1", "old-1"), _task("TASK-2", "old-2")])
    before = store.snapshot()
    store.fail_next_save_many = True

    with pytest.raises(InterruptedWriteError):
        store.save_many([_task("TASK-1", "new-1"), _task("TASK-2", "new-2")])

    assert store.snapshot() == before


def test_successful_write_after_interruption_replaces_checkpoint_atomically():
    store = InterruptedWriteTaskStateStore()
    store.save_many([_task("TASK-1", "old")])
    store.fail_next_save_many = True

    with pytest.raises(InterruptedWriteError):
        store.save_many([_task("TASK-1", "new"), _task("TASK-2", "new")])

    store.save_many([_task("TASK-1", "new"), _task("TASK-2", "new")])
    assert store.load("TASK-1")["title"] == "new"
    assert store.load("TASK-2")["title"] == "new"
