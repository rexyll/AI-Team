import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_result_store import DurableTaskResultStore


def _manager(store):
    return TaskManager(
        [Task(id="TASK-001", title="demo", description="demo", role="developer")],
        result_store=store,
    )


def test_task_manager_commits_result_before_terminal_transition(tmp_path):
    store = DurableTaskResultStore(tmp_path)
    manager = _manager(store)
    manager.mark_ready("TASK-001")
    manager.mark_running("TASK-001")

    task = manager.commit_task_result("TASK-001", "delivery-a", {"ok": True})

    assert task.status == "completed"
    assert task.result == {"ok": True}
    durable = store.get("TASK-001")
    assert durable is not None
    assert durable.delivery_key == "delivery-a"
    assert durable.status == "completed"
    assert durable.result == {"ok": True}


def test_duplicate_task_result_is_noop_for_task_mutation(tmp_path):
    store = DurableTaskResultStore(tmp_path)
    manager = _manager(store)
    manager.mark_ready("TASK-001")
    manager.mark_running("TASK-001")
    manager.commit_task_result("TASK-001", "delivery-a", {"value": 1})
    history_len = len(manager.get_task("TASK-001").status_history)

    task = manager.commit_task_result("TASK-001", "delivery-a", {"value": 999})

    assert task.result == {"value": 1}
    assert len(task.status_history) == history_len


def test_task_manager_can_reconcile_durable_result_after_restart(tmp_path):
    store = DurableTaskResultStore(tmp_path)
    store.commit("TASK-001", "delivery-a", {"ok": True})

    manager = _manager(store)
    manager.reconcile_durable_result("TASK-001")

    assert manager.get_task("TASK-001").status == "completed"
    assert manager.get_task("TASK-001").result == {"ok": True}


def test_task_manager_requires_result_store_for_durable_commit():
    manager = TaskManager([Task(id="TASK-001", title="demo", description="demo", role="developer")])
    with pytest.raises(RuntimeError, match="result_store"):
        manager.commit_task_result("TASK-001", "delivery-a", {"ok": True})
