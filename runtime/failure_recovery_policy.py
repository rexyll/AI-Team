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
        return RecoveryDecision(RecoveryAction.REPLAN, "failure requires specification re-planning")

    if classification.retryable and retry_attempt < max_retries:
        return RecoveryDecision(RecoveryAction.RETRY, "retry budget remains")

    if classification.repairable:
        return RecoveryDecision(RecoveryAction.REPAIR, "failure is repairable")

    if classification.retryable:
        return RecoveryDecision(RecoveryAction.BLOCK, "retry budget is exhausted")

    return RecoveryDecision(RecoveryAction.BLOCK, "no supported recovery action")
