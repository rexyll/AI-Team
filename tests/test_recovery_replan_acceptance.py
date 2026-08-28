import pytest

from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.failure_classification import FailureClass
from runtime.recovery_replan_acceptance import accept_replan
from runtime.recovery_replan_adapter import ReplanResult
from runtime.task import Task
from runtime.task_manager import TaskManager


def _result() -> ReplanResult:
    plan = {
        "project": "demo",
        "summary": "replacement",
        "tasks": [
            {
                "id": "NEW-001",
                "title": "new task",
                "description": "new task",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }
    return ReplanResult(
        task_id="TASK-001",
        plan=plan,
        execution_order=("NEW-001",),
        failure_reason="spec mismatch",
        failure_class=FailureClass.SPECIFICATION.value,
        attempt=0,
    )


def test_accept_replan_only_at_quiescent_point():
    manager = TaskManager([
        Task(id="TASK-001", title="old", description="old", role="developer", status="failed")
    ])

    result = _result()
    accepted = accept_replan(manager, result)

    assert accepted.result is result
    assert manager.get_task("TASK-001").status == "failed"
    assert [task.id for task in manager.get_all_tasks()] == ["TASK-001"]


def test_accept_replan_rejects_active_graph_without_mutation():
    manager = TaskManager([
        Task(id="TASK-001", title="old", description="old", role="developer", status="ready")
    ])

    with pytest.raises(RuntimeError, match="tasks are active"):
        accept_replan(manager, _result())

    assert manager.get_task("TASK-001").status == "ready"
    assert [task.id for task in manager.get_all_tasks()] == ["TASK-001"]


def test_accept_replan_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        accept_replan(object(), _result())

    manager = TaskManager([])
    with pytest.raises(TypeError):
        accept_replan(manager, object())
