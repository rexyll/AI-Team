from __future__ import annotations

from dataclasses import dataclass

from runtime.failure_classification import FailureClass
from runtime.failure_recovery_policy import RecoveryAction, RecoveryDecision
from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class RecoveryIntent:
    """A durable hand-off contract for recovery actions owned by higher layers."""

    action: RecoveryAction
    task_id: str
    failure_class: FailureClass
    failure_reason: str
    decision_reason: str
    attempt: int

    @property
    def reason(self) -> str:
        """Backward-compatible alias for the recovery decision rationale."""
        return self.decision_reason

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "task_id": self.task_id,
            "failure_class": self.failure_class.value,
            "failure_reason": self.failure_reason,
            "decision_reason": self.decision_reason,
            "attempt": self.attempt,
        }


class FailureRecoveryExecutor:
    """Execute only recovery primitives that are already owned by TaskManager."""

    def __init__(self, task_manager: TaskManager) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        self.task_manager = task_manager

    def execute(self, task_id: str, decision: RecoveryDecision) -> RecoveryIntent | None:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(decision, RecoveryDecision):
            raise TypeError("decision must be a RecoveryDecision")

        if decision.action is RecoveryAction.RETRY:
            self.task_manager.retry_task(
                task_id,
                reason=decision.failure_reason or decision.reason,
                retryable=True,
            )
            return None

        failure_reason = decision.failure_reason or decision.reason
        return RecoveryIntent(
            action=decision.action,
            task_id=task_id,
            failure_class=decision.failure_class,
            failure_reason=failure_reason,
            decision_reason=decision.reason,
            attempt=decision.retry_attempt,
        )
