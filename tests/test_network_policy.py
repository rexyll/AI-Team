import pytest

from security.network import NetworkPolicy, validate_network_url


def test_https_destination_requires_explicit_host_allow_list():
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))

    assert policy.validate_url("https://api.example.com/v1") == "https://api.example.com/v1"
    with pytest.raises(PermissionError):
        policy.validate_url("https://untrusted.example.com/v1")


def test_non_https_schemes_are_denied():
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))

    for url in (
        "http://api.example.com/v1",
        "ftp://api.example.com/file",
        "file:///tmp/secrets",
        "javascript:alert(1)",
    ):
        with pytest.raises(PermissionError):
            policy.validate_url(url)


def test_credential_bearing_urls_are_denied():
    policy = NetworkPolicy(allowed_hosts=frozenset({"api.example.com"}))

    with pytest.raises(PermissionError):
        policy.validate_url("https://user:secret@api.example.com/v1")


def test_default_policy_denies_all_destinations():
    policy = NetworkPolicy()

    assert policy.allows("https://api.example.com") is False


def test_validation_normalizes_host_case_and_trailing_dot():
    policy = NetworkPolicy(allowed_hosts=frozenset({"API.EXAMPLE.COM"}))

    assert policy.validate_url("https://api.example.com./v1") == "https://api.example.com./v1"


def test_convenience_validator_uses_explicit_allow_list():
    assert validate_network_url(
        "https://api.example.com/v1",
        allowed_hosts={"api.example.com"},
    ) == "https://api.example.com/v1"
