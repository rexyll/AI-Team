from __future__ import annotations

from mcp_bridge.error_contract import normalize_error
from mcp_bridge.observability import MCPOperationTracker
from mcp_bridge.sanitization import redact_secrets


def test_redacts_secret_bearing_string_patterns() -> None:
    value = "Authorization: Bearer super-token API_KEY=abc123 secret=hidden"
    redacted = redact_secrets(value)

    assert "super-token" not in redacted
    assert "abc123" not in redacted
    assert "hidden" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_sensitive_mapping_keys_recursively() -> None:
    value = {
        "api_key": "secret-value",
        "nested": {"password": "password-value", "safe": "visible"},
    }

    redacted = redact_secrets(value)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "visible"


def test_normalized_error_does_not_leak_secret() -> None:
    error = normalize_error(ValueError("bad request api_key=super-secret"))

    assert error["category"] == "invalid_request"
    assert "super-secret" not in error["message"]
    assert "[REDACTED]" in error["message"]


def test_operation_history_does_not_leak_sensitive_metadata() -> None:
    tracker = MCPOperationTracker()
    record = tracker.start(
        "test",
        policy_profile="readonly",
        policy_allowed=True,
        metadata={"api_token": "secret-token", "safe": "value"},
    )
    tracker.finish(
        record.operation_id,
        outcome="success",
        metadata={"authorization": "Bearer secret-token-2"},
    )

    history = tracker.history()
    metadata = history[0]["metadata"]

    assert metadata["api_token"] == "[REDACTED]"
    assert metadata["authorization"] == "[REDACTED]"
    assert metadata["safe"] == "value"
