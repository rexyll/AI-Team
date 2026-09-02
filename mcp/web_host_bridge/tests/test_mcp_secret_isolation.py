from __future__ import annotations

from web_host_bridge.error_contract import normalize_error
from web_host_bridge.observability import MCPOperationTracker
from web_host_bridge.sanitization import redact_secrets, redact_environment_values, sanitized_environment
from web_host_bridge.terminal import MCPTerminalCapabilityBoundary


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


def test_sanitized_environment_removes_credential_like_keys(monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_TEST_API_KEY", "secret-api-key")
    monkeypatch.setenv("AI_TEAM_TEST_ACCESS_TOKEN", "secret-access-token")
    monkeypatch.setenv("AI_TEAM_TEST_SECRET", "secret-value")
    monkeypatch.setenv("AI_TEAM_TEST_SAFE", "visible")

    environment = sanitized_environment()

    assert "AI_TEAM_TEST_API_KEY" not in environment
    assert "AI_TEAM_TEST_ACCESS_TOKEN" not in environment
    assert "AI_TEAM_TEST_SECRET" not in environment
    assert environment["AI_TEAM_TEST_SAFE"] == "visible"


def test_redacts_host_secret_values_from_tool_output(monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_TEST_API_KEY", "super-secret-value")

    redacted = redact_environment_values("tool printed super-secret-value")

    assert "super-secret-value" not in redacted
    assert "[REDACTED]" in redacted


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
        project_id="project-secret=hidden",
    )
    tracker.finish(
        record.operation_id,
        outcome="success",
        metadata={"authorization": "Bearer secret-token-2"},
    )

    history = tracker.history()
    item = history[0]
    metadata = item["metadata"]

    assert metadata["api_token"] == "[REDACTED]"
    assert metadata["authorization"] == "[REDACTED]"
    assert metadata["safe"] == "value"
    assert "hidden" not in item["project_id"]


def test_terminal_passes_sanitized_environment_and_redacts_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_TEST_API_KEY", "terminal-secret")
    captured = {}

    def fake_run_command(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return "exit_code=0\nterminal-secret"

    monkeypatch.setattr("web_host_bridge.terminal.run_command", fake_run_command)
    result = MCPTerminalCapabilityBoundary(str(tmp_path)).execute("python --version")

    assert "AI_TEAM_TEST_API_KEY" not in captured["env"]
    assert result["output"] == "[REDACTED]"
