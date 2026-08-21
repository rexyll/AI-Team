from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureKind(str, Enum):
    """Failure categories that determine whether another attempt is allowed."""

    EXECUTION = "execution"
    QUALITY_GATE = "quality_gate"
    INVALID_RESULT = "invalid_result"
    NON_RETRYABLE = "non_retryable"


@dataclass(frozen=True)
class RetryDecision:
    """Pure retry decision; it does not mutate Task lifecycle state."""

    retry: bool
    attempt: int
    max_retries: int
    failure_kind: FailureKind
    reason: str


def decide_retry(
    *,
    attempt: int,
    max_retries: int,
    failure_kind: FailureKind,
    reason: str,
) -> RetryDecision:
    """Decide whether a failed execution may be retried.

    ``attempt`` is the number of retries already consumed.  Therefore the
    next retry is allowed only while ``attempt < max_retries``.
    This function is intentionally side-effect free; TaskManager owns
    persistence of the resulting attempt history and lifecycle mutation.
    """
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        raise TypeError("attempt must be an integer")
    if attempt < 0:
        raise ValueError("attempt must be non-negative")

    if isinstance(max_retries, bool) or not isinstance(max_retries, int):
        raise TypeError("max_retries must be an integer")
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    if attempt > max_retries:
        raise ValueError("attempt cannot exceed max_retries")

    if not isinstance(failure_kind, FailureKind):
        raise TypeError("failure_kind must be a FailureKind")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")

    retry = (
        failure_kind != FailureKind.NON_RETRYABLE
        and attempt < max_retries
    )

    return RetryDecision(
        retry=retry,
        attempt=attempt + 1 if retry else attempt,
        max_retries=max_retries,
        failure_kind=failure_kind,
        reason=reason.strip(),
    )
