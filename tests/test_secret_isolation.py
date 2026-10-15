import pytest

from security.secrets import REDACTED, is_secret_key, redact_mapping, redact_text, redact_value


def test_secret_keys_are_case_insensitive():
    assert is_secret_key("AGNES_API_KEY")
    assert is_secret_key("Authorization")
    assert is_secret_key("client_secret")
    assert not is_secret_key("task_id")


def test_redact_mapping_detaches_and_redacts_nested_secret_values():
    source = {
        "api_key": "super-secret",
        "metadata": {"Authorization": "Bearer abc123", "safe": "value"},
        "items": [{"token": "nested-secret"}],
    }

    sanitized = redact_mapping(source)

    assert sanitized["api_key"] == REDACTED
    assert sanitized["metadata"]["Authorization"] == REDACTED
    assert sanitized["metadata"]["safe"] == "value"
    assert sanitized["items"][0]["token"] == REDACTED
    assert source["api_key"] == "super-secret"


def test_redact_text_removes_common_inline_secret_assignments():
    text = "request api_key=super-secret token:abc123 safe=value"

    sanitized = redact_text(text)

    assert "super-secret" not in sanitized
    assert "abc123" not in sanitized
    assert "safe=value" in sanitized
    assert sanitized.count(REDACTED) == 2


def test_redact_value_preserves_non_secret_scalars():
    assert redact_value("ordinary text") == "ordinary text"
    assert redact_value(42) == 42
    assert redact_value(None) is None


def test_redact_mapping_requires_mapping():
    with pytest.raises(TypeError):
        redact_mapping(["not", "a", "mapping"])
