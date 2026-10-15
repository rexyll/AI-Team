from __future__ import annotations

import pytest

from core.orchestrator import Orchestrator
from runtime.failure_classification import FailureClass, classify_failure
from runtime.failure_recovery_policy import RecoveryAction, decide_recovery
from runtime.task import Task
from runtime.task_manager import TaskManager


class _Router:
    def get_agent(self, role):
        raise AssertionError("agent execution is not part of this acceptance contract")


@pytest.mark.parametrize(
    ("failure_class", "retry_attempt", "max_retries", "expected"),
    [
        (FailureClass.TRANSIENT, 0, 1, RecoveryAction.RETRY),
        (FailureClass.TRANSIENT, 1, 1, RecoveryAction.BLOCK),
        (FailureClass.SPECIFICATION, 0, 1, RecoveryAction.REPLAN),
        (FailureClass.TOOL, 0, 1, RecoveryAction.RETRY),
        (FailureClass.DEPENDENCY, 0, 1, RecoveryAction.REPAIR),
    ],
)
def test_recovery_matrix_has_one_canonical_action(
    failure_class: FailureClass,
    retry_attempt: int,
    max_retries: int,
    expected: RecoveryAction,
):
    decision = decide_recovery(
        classify_failure(failure_class=failure_class, reason="acceptance"),
        retry_attempt=retry_attempt,
        max_retries=max_retries,
    )
    assert decision.action is expected
    assert decision.failure_class is failure_class
    assert decision.failure_reason == "acceptance"


def test_retry_exhaustion_is_terminal_without_mutating_retry_budget():
    task = Task(
        id="TASK-DEV-ACCEPT-001",
        title="developer acceptance",
        description="retry exhaustion",
        role="developer",
        max_retries=1,
    )
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "first failure")

    orchestrator = Orchestrator(manager, _Router())
    assert orchestrator._apply_retry_policy(task, RuntimeError("first failure")) is True
    assert task.retry_attempt == 1
    assert task.status == "ready"

    manager.mark_running(task.id)
    manager.mark_failed(task.id, "second failure")
    assert orchestrator._apply_retry_policy(task, RuntimeError("second failure")) is False

    assert task.status == "failed"
    assert task.retry_attempt == 1
    assert len(task.retry_history) == 1
    assert task.error == "second failure"


def test_non_retryable_terminal_failure_never_becomes_success():
    task = Task(
        id="TASK-DEV-ACCEPT-002",
        title="developer acceptance",
        description="terminal failure",
        role="developer",
        max_retries=2,
    )
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "invalid configuration")

    orchestrator = Orchestrator(manager, _Router())
    assert orchestrator._apply_retry_policy(task, ValueError("invalid configuration")) is False

    assert task.status == "failed"
    assert task.retry_attempt == 0
    assert task.retry_history == []
    assert task.error == "invalid configuration"
