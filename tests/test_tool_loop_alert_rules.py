from types import SimpleNamespace

import pytest

from runtime.tool_loop_alert_rules import duplicate_tool_call_rule, retry_tool_call_rule, result_volume_rule


def _snapshot(*items):
    return SimpleNamespace(tool_calls=list(items))


def _call(*, duplicate=None, retry=None, chars=0):
    return SimpleNamespace(duplicate_of=duplicate, retry_of=retry, result_chars=chars)


def test_duplicate_tool_call_rule_detects_repeated_calls():
    rule = duplicate_tool_call_rule(threshold=2)
    assert rule.condition(_snapshot(_call(duplicate="a"), _call(duplicate="b")))
    assert not rule.condition(_snapshot(_call(duplicate="a")))


def test_retry_tool_call_rule_detects_retries_only():
    rule = retry_tool_call_rule(threshold=2)
    assert rule.condition(_snapshot(_call(retry="a"), _call(retry="b")))
    assert not rule.condition(_snapshot(_call(duplicate="a"), _call()))


def test_result_volume_rule_detects_large_tool_evidence():
    rule = result_volume_rule(threshold_chars=100)
    assert rule.condition(_snapshot(_call(chars=60), _call(chars=40)))
    assert not rule.condition(_snapshot(_call(chars=99)))


def test_tool_loop_thresholds_are_positive():
    with pytest.raises(ValueError):
        duplicate_tool_call_rule(threshold=0)
    with pytest.raises(ValueError):
        retry_tool_call_rule(threshold=0)
    with pytest.raises(ValueError):
        result_volume_rule(threshold_chars=0)
