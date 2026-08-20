import pytest

from agents.tester import TesterAgent as _TesterAgent


def test_tester_parses_passed():
    assert _TesterAgent._parse_result("TEST_PASSED\nall tests pass") == "passed"


def test_tester_parses_failed():
    assert _TesterAgent._parse_result("TEST_FAILED\nmissing edge case") == "failed"


def test_tester_rejects_invalid_result():
    with pytest.raises(ValueError, match="invalid decision"):
        _TesterAgent._parse_result("looks good")
