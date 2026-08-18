import pytest

from agents.tester import TesterAgent


def test_tester_parses_passed():
    assert TesterAgent._parse_result("TEST_PASSED\nall tests pass") == "passed"


def test_tester_parses_failed():
    assert TesterAgent._parse_result("TEST_FAILED\nmissing edge case") == "failed"


def test_tester_rejects_invalid_result():
    with pytest.raises(ValueError, match="invalid decision"):
        TesterAgent._parse_result("looks good")
