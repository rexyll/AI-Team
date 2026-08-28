from __future__ import annotations

import pytest

from runtime.failure_classification import FailureClass, classify_failure
from runtime.failure_recovery_executor import FailureRecoveryExecutor, RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction, RecoveryDecision, decide_recovery
from runtime.task import Task
from runtime.task_manager import TaskManager


def _manager() -> TaskManager:
    manager = TaskManager()
    manager.add_task(Task(id="TASK-001", title="demo", description="demo", role="developer"))
    manager.mark_ready("TASK-001")
    manager.mark_running("TASK-001")
    manager.mark_failed("TASK-001", "transient failure")
    manager.configure_retry("TASK-001", max_retries=2)
    return manager


def test_retry_delegates_to_existing_task_manager_primitive():
    manager = _manager()
    executor = FailureRecoveryExecutor(manager)
    decision = decide_recovery(
        classify_failure(failure_class=FailureClass.TRANSIENT, reason="network reset"),
        retry_attempt=0,
        max_retries=2,
    )

    assert executor.execute("TASK-001", decision) is None
    task = manager.get_task("TASK-001")
    assert task.status == "ready"
    assert task.retry_attempt == 1
    assert task.retry_history[-1]["reason"] == "network reset"
    assert task.error is None


def test_non_retry_actions_return_intent_without_mutating_task():
    manager = _manager()
    executor = FailureRecoveryExecutor(manager)

    for action in (RecoveryAction.REPAIR, RecoveryAction.REPLAN, RecoveryAction.BLOCK):
        before = manager.get_task("TASK-001").to_dict()
        decision = RecoveryDecision(action=action, reason="higher layer required")
        intent = executor.execute("TASK-001", decision)

        assert isinstance(intent, RecoveryIntent)
        assert intent.to_dict() == {
            "action": action.value,
            "task_id": "TASK-001",
            "reason": "higher layer required",
        }
        assert manager.get_task("TASK-001").to_dict() == before


def test_executor_rejects_invalid_inputs():
    manager = _manager()
    executor = FailureRecoveryExecutor(manager)
    decision = RecoveryDecision(RecoveryAction.BLOCK, "blocked")

    with pytest.raises(ValueError, match="task_id"):
        executor.execute("", decision)
    with pytest.raises(TypeError, match="RecoveryDecision"):
        executor.execute("TASK-001", object())
