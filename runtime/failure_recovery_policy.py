from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from runtime.failure_classification import FailureClassification


class RecoveryAction(str, Enum):
    RETRY = "retry"
    REPAIR = "repair"
    REPLAN = "replan"
    BLOCK = "block"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    failure_reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action.value, "reason": self.reason}


def decide_recovery(
    classification: FailureClassification,
    *,
    retry_attempt: int = 0,
    max_retries: int = 0,
) -> RecoveryDecision:
    """Select a recovery action without executing it."""
    if retry_attempt < 0 or max_retries < 0:
        raise ValueError("retry counters must be non-negative")
    if retry_attempt > max_retries:
        raise ValueError("retry_attempt cannot exceed max_retries")

    if classification.replan_required:
        reason = "failure requires specification re-planning"
    elif classification.retryable and retry_attempt < max_retries:
        reason = "retry budget remains"
    elif classification.repairable:
        reason = "failure is repairable"
    elif classification.retryable:
        reason = "retry budget is exhausted"
    else:
        reason = "no supported recovery action"

    if classification.replan_required:
        action = RecoveryAction.REPLAN
    elif classification.retryable and retry_attempt < max_retries:
        action = RecoveryAction.RETRY
    elif classification.repairable:
        action = RecoveryAction.REPAIR
    elif classification.retryable:
        action = RecoveryAction.BLOCK
    else:
        action = RecoveryAction.BLOCK

    return RecoveryDecision(
        action=action,
        reason=reason,
        failure_reason=classification.reason,
    )
