from types import SimpleNamespace

import pytest

from runtime.review_alert_rules import recovery_rule, reviewer_rejection_rule


def _snapshot(*tasks):
    return SimpleNamespace(tasks=tasks)


def _task(*, reviews=None, retries=None):
    return SimpleNamespace(review_history=reviews or [], retry_history=retries or [])


def test_reviewer_rejection_rule_detects_repeated_rejections():
    rule = reviewer_rejection_rule(threshold=2)
    task = _task(reviews=[{"status": "rejected"}, {"status": "changes_requested"}])
    assert rule.condition(_snapshot(task))


def test_reviewer_rejection_rule_does_not_alert_on_approved_history():
    rule = reviewer_rejection_rule(threshold=2)
    task = _task(reviews=[{"status": "approved"}, {"status": "approved"}])
    assert not rule.condition(_snapshot(task))


def test_recovery_rule_detects_retry_pressure():
    rule = recovery_rule(threshold=2)
    task = _task(retries=[{"retryable": True}, {"retryable": True}])
    assert rule.condition(_snapshot(task))


def test_recovery_rule_does_not_alert_without_recovery_pressure():
    rule = recovery_rule(threshold=2)
    task = _task(retries=[{"retryable": True}])
    assert not rule.condition(_snapshot(task))


def test_review_and_recovery_thresholds_are_positive():
    with pytest.raises(ValueError):
        reviewer_rejection_rule(threshold=0)
    with pytest.raises(ValueError):
        recovery_rule(threshold=0)
