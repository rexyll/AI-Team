from __future__ import annotations

import pytest

from runtime.failure_classification import FailureClass, classify_failure
from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction, decide_recovery
from runtime.recovery_replan_coordinator import RecoveryReplanCoordinator
from runtime.task import Task
from runtime.task_manager import TaskManager


def _intent() -> RecoveryIntent:
    classification = classify_failure(
        failure_class=FailureClass.SPECIFICATION,
        reason="requirements conflict",
    )
    decision = decide_recovery(classification, retry_attempt=0, max_retries=0)
    return RecoveryIntent(
        action=decision.action,
        task_id="TASK-001",
        failure_class=decision.failure_class,
        failure_reason=decision.failure_reason,
        decision_reason=decision.reason,
        attempt=decision.retry_attempt,
    )


def _manager() -> TaskManager:
    return TaskManager(
        [Task(id="TASK-001", title="old", description="old", role="developer")]
    )


def _planner(_: str) -> dict:
    return {
        "project": "demo",
        "summary": "replacement",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "new",
                "description": "new description",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def test_prepare_is_side_effect_free_and_commit_swaps_graph():
    manager = _manager()
    coordinator = RecoveryReplanCoordinator(manager, _planner)

    outcome = coordinator.prepare(_intent(), "produce replacement plan")
    assert manager.get_task("TASK-001").title == "old"

    coordinator.commit(outcome)
    assert manager.get_task("TASK-001").title == "new"
    assert manager.get_task("TASK-001").status == "pending"


def test_prepare_rejects_active_graph_without_mutation():
    manager = _manager()
    manager.mark_ready("TASK-001")
    coordinator = RecoveryReplanCoordinator(manager, _planner)

    with pytest.raises(RuntimeError, match="tasks are active"):
        coordinator.prepare(_intent(), "produce replacement plan")

    assert manager.get_task("TASK-001").title == "old"


def test_commit_rejects_invalid_outcome():
    coordinator = RecoveryReplanCoordinator(_manager(), _planner)
    with pytest.raises(TypeError):
        coordinator.commit(object())
