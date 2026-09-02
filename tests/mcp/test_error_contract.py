from __future__ import annotations

from mcp_bridge.error_contract import normalize_error
from mcp_bridge.errors import MCPBridgeConfigurationError, MCPBridgeError, MCPBridgePolicyError


def test_policy_error_has_stable_category() -> None:
    error = normalize_error(MCPBridgePolicyError("denied"))
    assert error["category"] == "policy_denied"
    assert error["type"] == "MCPBridgePolicyError"
    assert error["message"] == "denied"


def test_configuration_error_has_stable_category() -> None:
    error = normalize_error(MCPBridgeConfigurationError("invalid transport"))
    assert error["category"] == "configuration_error"


def test_value_error_is_invalid_request() -> None:
    assert normalize_error(ValueError("bad input"))["category"] == "invalid_request"


def test_timeout_is_execution_error() -> None:
    assert normalize_error(TimeoutError("timed out"))["category"] == "execution_error"


def test_file_not_found_is_not_found() -> None:
    assert normalize_error(FileNotFoundError("missing"))["category"] == "not_found"


def test_unknown_mcp_category_falls_back_to_bridge_error() -> None:
    error = MCPBridgeError("internal failure")
    error.error_category = "unstable_internal_category"
    assert normalize_error(error)["category"] == "bridge_error"


def test_normalized_error_redacts_secrets() -> None:
    error = normalize_error(ValueError("authorization=Bearer super-secret-token"))
    assert error["message"] == "authorization=[REDACTED]"
