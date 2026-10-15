from types import SimpleNamespace

import pytest

from runtime.alert_rules import failure_rate_rule, latency_rule, retry_rule


def snapshot(*, total=10, failed=0, average=None, retries=0):
    return SimpleNamespace(workflow=SimpleNamespace(
        total_tasks=total, failed=failed, average_duration_seconds=average, retries=retries
    ))


def test_failure_rate_rule_is_thresholded_and_fail_closed_for_empty_workflow():
    rule = failure_rate_rule(threshold=0.5)
    assert rule.condition(snapshot(total=10, failed=5))
    assert not rule.condition(snapshot(total=10, failed=4))
    assert not rule.condition(snapshot(total=0, failed=0))


def test_latency_rule_uses_average_duration():
    rule = latency_rule(threshold_seconds=30)
    assert rule.condition(snapshot(average=30))
    assert not rule.condition(snapshot(average=29.9))
    assert not rule.condition(snapshot(average=None))


def test_retry_rule_requires_positive_threshold():
    with pytest.raises(ValueError):
        retry_rule(threshold=0)
    rule = retry_rule(threshold=3)
    assert rule.condition(snapshot(retries=3))
    assert not rule.condition(snapshot(retries=2))
