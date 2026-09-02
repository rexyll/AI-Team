from __future__ import annotations

from mcp_bridge.error_contract import normalize_error
from mcp_bridge.errors import MCPBridgePolicyError


def test_policy_error_has_stable_category() -> None:
    error = normalize_error(MCPBridgePolicyError("denied"))
    assert error["category"] == "policy_denied"
    assert error["type"] == "MCPBridgePolicyError"
    assert error["message"] == "denied"


def test_value_error_is_invalid_request() -> None:
    assert normalize_error(ValueError("bad input"))["category"] == "invalid_request"


def test_timeout_is_execution_error() -> None:
    assert normalize_error(TimeoutError("timed out"))["category"] == "execution_error"
