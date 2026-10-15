from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    TOOL = "tool"
    TEST = "test"
    IMPLEMENTATION = "implementation"
    DEPENDENCY = "dependency"
    SPECIFICATION = "specification"
    AGENT = "agent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureClassification:
    failure_class: FailureClass
    retryable: bool
    repairable: bool
    replan_required: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class.value,
            "retryable": self.retryable,
            "repairable": self.repairable,
            "replan_required": self.replan_required,
            "reason": self.reason,
        }


def classify_failure(
    *,
    failure_class: FailureClass | str,
    reason: str,
) -> FailureClassification:
    """Normalize a known failure category without executing recovery."""
    try:
        category = (
            failure_class
            if isinstance(failure_class, FailureClass)
            else FailureClass(failure_class)
        )
    except ValueError as exc:
        raise ValueError(f"Invalid failure class: {failure_class}") from exc

    if not reason.strip():
        raise ValueError("failure reason must not be empty")

    retryable = category in {FailureClass.TRANSIENT, FailureClass.TOOL}
    repairable = category in {
        FailureClass.TEST,
        FailureClass.IMPLEMENTATION,
        FailureClass.DEPENDENCY,
        FailureClass.AGENT,
    }
    replan_required = category == FailureClass.SPECIFICATION

    return FailureClassification(
        failure_class=category,
        retryable=retryable,
        repairable=repairable,
        replan_required=replan_required,
        reason=reason.strip(),
    )
