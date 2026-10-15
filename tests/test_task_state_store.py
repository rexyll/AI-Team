from runtime.task import Task
from runtime.task_state_store import InMemoryTaskStateStore


def test_task_state_store_round_trips_a_snapshot_without_aliasing():
    task = Task(id="TASK-STATE", title="state", description="persist", role="developer")
    task.context["key"] = "value"
    store = InMemoryTaskStateStore()
    store.save(task)
    task.context["key"] = "mutated"
    saved = store.load(task.id)
    assert saved["context"]["key"] == "value"
    saved["context"]["key"] = "changed"
    assert store.load(task.id)["context"]["key"] == "value"


def test_task_state_store_snapshot_is_independent():
    task = Task(id="TASK-STATE", title="state", description="persist", role="developer")
    store = InMemoryTaskStateStore()
    store.save(task)
    snapshot = store.snapshot()
    snapshot[task.id]["title"] = "changed"
    assert store.load(task.id)["title"] == "state"
