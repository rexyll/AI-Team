import pytest

from runtime.atomic_task_state_store import AtomicTaskStateStore
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.workflow_checkpoint import WorkflowCheckpoint


@pytest.fixture(params=[InMemoryTaskStateStore, AtomicTaskStateStore])
def state_store(request):
    return request.param()


def _tasks():
    return [
        Task("TASK-001", "first", "first task", "developer"),
        Task("TASK-002", "second", "second task", "tester", dependencies=["TASK-001"]),
    ]


def test_state_store_round_trip_preserves_task_manager_authoritative_snapshot(state_store):
    manager = TaskManager(_tasks())
    manager.mark_ready("TASK-001")
    manager.mark_running("TASK-001")
    manager.mark_developer_completed("TASK-001", {"status": "completed", "data": {"value": 42}})

    state_store.save_many(manager.get_all_tasks())
    restored = [Task.from_dict(payload) for payload in state_store.snapshot().values()]
    restored_manager = TaskManager(restored)

    assert [task.to_dict() for task in restored_manager.get_all_tasks()] == [
        task.to_dict() for task in manager.get_all_tasks()
    ]


def test_state_store_batch_save_is_atomic_before_commit(state_store):
    state_store.save(Task("TASK-EXISTING", "existing", "existing", "developer"))

    with pytest.raises(TypeError):
        state_store.save_many([
            Task("TASK-NEW", "new", "new", "developer"),
            object(),
        ])

    assert set(state_store.snapshot()) == {"TASK-EXISTING"}


def test_checkpoint_and_durable_snapshot_restore_to_equivalent_task():
    task = Task("TASK-CHECKPOINT", "checkpoint", "restore", "developer")
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    task.context["source"] = "durable"

    checkpoint = WorkflowCheckpoint.capture(task)
    store = InMemoryTaskStateStore()
    store.save(task)

    checkpoint_task = checkpoint.restore()
    durable_task = Task.from_dict(store.load(task.id))

    assert checkpoint_task.to_dict() == durable_task.to_dict()
    assert checkpoint_task.to_dict() == manager.get_task(task.id).to_dict()
