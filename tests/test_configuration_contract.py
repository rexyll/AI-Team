from __future__ import annotations

import pytest

from config.configuration import ConfigurationError, configuration_precedence, load_configuration
from config.model import resolve_developer_llm_spec, resolve_role_llm_spec


def _configure(monkeypatch, *, provider="agnes", model="model-default"):
    monkeypatch.setenv("LLM_PROVIDERS", provider)
    monkeypatch.setenv("DEFAULT_PROVIDER", provider)
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "test-key")
    monkeypatch.setenv(f"{provider.upper()}_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv(f"{provider.upper()}_MODEL", model)


def test_configuration_resolves_all_roles_without_creating_clients(monkeypatch):
    _configure(monkeypatch)
    config = load_configuration()

    assert [item.role for item in config.roles] == [
        "planner", "architect", "developer", "tester", "reviewer", "analyst", "doc_writer"
    ]
    assert config.role("developer").provider == "agnes"
    assert config.role("developer").model == "model-default"
    assert config.provider("agnes").base_url == "https://example.test/v1"


def test_role_specific_provider_and_model_override_defaults(monkeypatch):
    _configure(monkeypatch, provider="agnes", model="agnes-default")
    monkeypatch.setenv("LLM_PROVIDERS", "agnes,other")
    monkeypatch.setenv("OTHER_API_KEY", "other-key")
    monkeypatch.setenv("OTHER_BASE_URL", "https://other.test/v1")
    monkeypatch.setenv("OTHER_MODEL", "other-default")
    monkeypatch.setenv("TESTER_PROVIDER", "other")
    monkeypatch.setenv("TESTER_MODEL", "tester-model")

    assert resolve_role_llm_spec("tester") == ("other", "tester-model")
    assert resolve_role_llm_spec("planner") == ("agnes", "agnes-default")


def test_model_falls_back_from_role_to_provider_to_default(monkeypatch):
    _configure(monkeypatch, model="provider-model")
    monkeypatch.setenv("DEFAULT_MODEL", "global-model")
    monkeypatch.delenv("DEVELOPER_MODEL", raising=False)
    assert resolve_role_llm_spec("developer") == ("agnes", "provider-model")

    monkeypatch.delenv("AGNES_MODEL", raising=False)
    assert resolve_role_llm_spec("developer") == ("agnes", "global-model")


def test_developer_instance_override_precedes_shared_developer(monkeypatch):
    _configure(monkeypatch, model="provider-model")
    monkeypatch.setenv("DEVELOPER_COUNT", "2")
    monkeypatch.setenv("DEVELOPER_MODEL", "shared-model")
    monkeypatch.setenv("DEVELOPER_2_MODEL", "instance-model")
    config = load_configuration()

    assert config.developer_count == 2
    assert resolve_developer_llm_spec(2) == ("agnes", "instance-model")
    assert resolve_developer_llm_spec(1) == ("agnes", "shared-model")


def test_invalid_provider_configuration_fails_before_client_creation(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "agnes")
    monkeypatch.setenv("AGNES_API_KEY", "test-key")
    monkeypatch.delenv("AGNES_BASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="AGNES_BASE_URL"):
        load_configuration()


def test_invalid_developer_count_is_rejected(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("DEVELOPER_COUNT", "0")

    with pytest.raises(ConfigurationError, match="DEVELOPER_COUNT"):
        load_configuration()


def test_precedence_contract_is_stable():
    assert configuration_precedence() == (
        "role-specific provider/model",
        "provider default model",
        "DEFAULT_MODEL",
        "for Developer N: DEVELOPER_N_* then DEVELOPER_* then shared defaults",
    )
