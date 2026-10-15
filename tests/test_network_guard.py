import pytest

from security.network import NetworkPolicy
from security.network_guard import NetworkEgressDenied, execute_network_operation


def test_allowed_destination_reaches_operation_with_original_url():
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))
    seen = []

    result = execute_network_operation(
        policy,
        "https://api.example.com./v1",
        lambda url: seen.append(url) or "ok",
    )

    assert result == "ok"
    assert seen == ["https://api.example.com./v1"]


def test_denied_destination_never_invokes_operation():
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))
    called = False

    def operation(url):
        nonlocal called
        called = True
        return url

    with pytest.raises(NetworkEgressDenied):
        execute_network_operation(policy, "https://untrusted.example.com", operation)

    assert called is False


def test_default_policy_denies_before_operation():
    called = False

    def operation(url):
        nonlocal called
        called = True
        return url

    with pytest.raises(NetworkEgressDenied):
        execute_network_operation(NetworkPolicy(), "https://api.example.com", operation)

    assert called is False


def test_guard_rejects_invalid_inputs_before_execution():
    with pytest.raises(TypeError):
        execute_network_operation("not-a-policy", "https://api.example.com", lambda _: None)
    with pytest.raises(TypeError):
        execute_network_operation(NetworkPolicy(), "https://api.example.com", None)
