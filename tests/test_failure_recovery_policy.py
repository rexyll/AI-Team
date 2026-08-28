from __future__ import annotations

import pytest

from runtime.failure_classification import FailureClass, classify_failure
from runtime.failure_recovery_policy import RecoveryAction, decide_recovery


def _classification(category: FailureClass):
    return classify_failure(failure_class=category, reason="observed failure")


@pytest.mark.parametrize(
    ("category", "attempt", "maximum", "expected"),
    [
        (FailureClass.TRANSIENT, 0, 2, RecoveryAction.RETRY),
        (FailureClass.TOOL, 1, 2, RecoveryAction.RETRY),
        (FailureClass.TRANSIENT, 2, 2, RecoveryAction.BLOCK),
        (FailureClass.TEST, 0, 2, RecoveryAction.REPAIR),
        (FailureClass.IMPLEMENTATION, 0, 0, RecoveryAction.REPAIR),
        (FailureClass.DEPENDENCY, 0, 0, RecoveryAction.REPAIR),
        (FailureClass.AGENT, 0, 0, RecoveryAction.REPAIR),
        (FailureClass.SPECIFICATION, 0, 2, RecoveryAction.REPLAN),
        (FailureClass.UNKNOWN, 0, 2, RecoveryAction.BLOCK),
    ],
)
def test_recovery_policy_selects_action_without_executing_it(
    category, attempt, maximum, expected
):
    decision = decide_recovery(
        _classification(category), retry_attempt=attempt, max_retries=maximum
    )
    assert decision.action is expected
    assert decision.reason


def test_recovery_policy_prefers_replan_for_specification_failure():
    decision = decide_recovery(
        _classification(FailureClass.SPECIFICATION), retry_attempt=2, max_retries=2
    )
    assert decision.action is RecoveryAction.REPLAN


def test_recovery_policy_rejects_invalid_retry_counters():
    classification = _classification(FailureClass.TRANSIENT)

    with pytest.raises(ValueError, match="non-negative"):
        decide_recovery(classification, retry_attempt=-1, max_retries=2)

    with pytest.raises(ValueError, match="cannot exceed"):
        decide_recovery(classification, retry_attempt=3, max_retries=2)


def test_recovery_decision_serializes_stably():
    decision = decide_recovery(
        _classification(FailureClass.TEST), retry_attempt=0, max_retries=1
    )
    assert decision.to_dict() == {
        "action": "repair",
        "reason": "failure is repairable",
    }
