import pytest

from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.failure_classification import FailureClass
from runtime.recovery_replan_acceptance import ReplanAcceptance
from runtime.recovery_replan_adapter import ReplanResult
from runtime.recovery_replan_replacement import materialize_replacement
from runtime.task import Task
from runtime.task_manager import TaskManager


def _intent() -> RecoveryIntent:
    return RecoveryIntent(
        action=RecoveryAction.REPLAN,
        task_id="TASK-001",
        failure_class=FailureClass.SPECIFICATION,
        failure_reason="requirements changed",
        decision_reason="re-plan required",
        attempt=1,
    )


def _acceptance(tasks: list[dict]) -> ReplanAcceptance:
    plan = {
        "project": "demo",
        "summary": "replacement",
        "tasks": tasks,
    }
    result = ReplanResult(
        task_id="TASK-001",
        plan=plan,
        execution_order=tuple(item["id"] for item in tasks),
        failure_reason="requirements changed",
        failure_class="specification",
        attempt=1,
    )
    return ReplanAcceptance(result=result)


def test_materialize_replacement_does_not_mutate_live_manager():
    task = Task(id="TASK-001", title="old", description="old", role="developer", status="completed")
    manager = TaskManager([task])
    acceptance = _acceptance([
        {
            "id": "TASK-001",
            "title": "new",
            "description": "new",
            "role": "developer",
            "dependencies": [],
        },
        {
            "id": "TASK-002",
            "title": "followup",
            "description": "followup",
            "role": "tester",
            "dependencies": ["TASK-001"],
        },
    ])

    replacement = materialize_replacement(manager, acceptance)

    assert [item.id for item in replacement.tasks] == ["TASK-001", "TASK-002"]
    assert replacement.tasks[0].status == "completed"
    assert replacement.tasks[0].title == "new"
    assert manager.get_task("TASK-001") is task
    assert manager.get_task("TASK-001").title == "old"


def test_materialize_replacement_rejects_active_live_graph():
    manager = TaskManager([
        Task(id="TASK-001", title="old", description="old", role="developer", status="running")
    ])

    with pytest.raises(RuntimeError, match="tasks are active"):
        materialize_replacement(manager, _acceptance([
            {
                "id": "TASK-001",
                "title": "new",
                "description": "new",
                "role": "developer",
                "dependencies": [],
            }
        ]))


def test_materialize_replacement_rejects_discarding_completed_history():
    manager = TaskManager([
        Task(id="TASK-001", title="done", description="done", role="developer", status="completed"),
        Task(id="TASK-002", title="old", description="old", role="tester", status="failed"),
    ])

    with pytest.raises(ValueError, match="completed task history"):
        materialize_replacement(manager, _acceptance([
            {
                "id": "TASK-002",
                "title": "new",
                "description": "new",
                "role": "tester",
                "dependencies": [],
            }
        ]))


def test_materialize_replacement_requires_acceptance_contract():
    manager = TaskManager([])
    with pytest.raises(TypeError, match="acceptance"):
        materialize_replacement(manager, object())
