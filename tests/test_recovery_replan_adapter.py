import pytest

from runtime.failure_classification import FailureClass
from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.recovery_replan_adapter import RecoveryReplanAdapter


def _intent(action=RecoveryAction.REPLAN):
    return RecoveryIntent(
        action=action,
        task_id="TASK-REPLAN-001",
        failure_class=FailureClass.SPECIFICATION,
        failure_reason="requirements are inconsistent",
        decision_reason="the current plan cannot satisfy the specification",
        attempt=1,
    )


def _plan():
    return {
        "project": "replanned project",
        "summary": "replacement plan",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "foundation",
                "description": "build foundation",
                "role": "developer",
                "dependencies": [],
            },
            {
                "id": "TASK-002",
                "title": "feature",
                "description": "build feature",
                "role": "developer",
                "dependencies": ["TASK-001"],
            },
        ],
    }


def test_replan_prepares_validated_plan_and_dependency_order_without_mutating_live_state():
    calls = []

    def planner(requirement):
        calls.append(requirement)
        return _plan()

    adapter = RecoveryReplanAdapter(planner)
    result = adapter.prepare(_intent(), "updated requirements")

    assert calls == ["updated requirements"]
    assert result.task_id == "TASK-REPLAN-001"
    assert result.execution_order == ("TASK-001", "TASK-002")
    assert result.failure_reason == "requirements are inconsistent"
    assert result.failure_class == "specification"
    assert result.attempt == 1
    assert result.plan == _plan()


def test_replan_rejects_invalid_plan_before_it_can_be_consumed():
    def planner(_):
        plan = _plan()
        plan["tasks"][1]["dependencies"] = ["MISSING"]
        return plan

    with pytest.raises(ValueError, match="unknown task"):
        RecoveryReplanAdapter(planner).prepare(_intent(), "updated requirements")


def test_replan_adapter_does_not_accept_non_replan_intent():
    with pytest.raises(ValueError, match="REPLAN"):
        RecoveryReplanAdapter(lambda _: _plan()).prepare(
            _intent(RecoveryAction.REPAIR),
            "updated requirements",
        )


def test_replan_adapter_rejects_empty_requirement():
    with pytest.raises(ValueError, match="non-empty"):
        RecoveryReplanAdapter(lambda _: _plan()).prepare(_intent(), " ")
