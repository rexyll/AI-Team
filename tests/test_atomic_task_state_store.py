import pytest

from runtime.atomic_task_state_store import AtomicTaskStateStore
from runtime.task import Task


def _task(task_id: str) -> Task:
    return Task(task_id, task_id, "atomic", "developer")


def test_save_many_commits_a_consistent_batch_snapshot():
    store = AtomicTaskStateStore()
    tasks = [_task("TASK-1"), _task("TASK-2")]
    store.save_many(tasks)
    assert set(store.snapshot()) == {"TASK-1", "TASK-2"}
    tasks[0].title = "mutated"
    assert store.load("TASK-1")["title"] == "TASK-1"


def test_save_many_validates_before_mutating_store():
    store = AtomicTaskStateStore()
    store.save(_task("TASK-EXISTING"))
    with pytest.raises(TypeError):
        store.save_many([_task("TASK-NEW"), object()])
    assert set(store.snapshot()) == {"TASK-EXISTING"}


def test_save_many_rejects_duplicate_ids_before_commit():
    store = AtomicTaskStateStore()
    with pytest.raises(ValueError):
        store.save_many([_task("TASK-DUP"), _task("TASK-DUP")])
    assert store.snapshot() == {}
