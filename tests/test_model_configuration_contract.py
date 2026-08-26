import pytest

from config import model as model_config


def _configure(monkeypatch):
    # These contracts validate precedence from a controlled environment. A
    # developer's local .env may legitimately contain role-specific settings;
    # those must not leak into a test that explicitly configures defaults.
    for role in ("PLANNER", "ARCHITECT", "DEVELOPER", "TESTER", "REVIEWER"):
        monkeypatch.delenv(f"{role}_PROVIDER", raising=False)
        monkeypatch.delenv(f"{role}_MODEL", raising=False)
    monkeypatch.delenv("DEVELOPER_PROVIDER", raising=False)
    monkeypatch.delenv("DEVELOPER_MODEL", raising=False)
    for index in range(1, 10):
        monkeypatch.delenv(f"DEVELOPER_{index}_PROVIDER", raising=False)
        monkeypatch.delenv(f"DEVELOPER_{index}_MODEL", raising=False)

    monkeypatch.setenv("LLM_PROVIDERS", "alpha,beta")
    monkeypatch.setenv("DEFAULT_PROVIDER", "alpha")
    monkeypatch.setenv("DEFAULT_MODEL", "alpha-default")
    monkeypatch.setenv("ALPHA_API_KEY", "alpha-key")
    monkeypatch.setenv("ALPHA_BASE_URL", "https://alpha.example/v1")
    monkeypatch.setenv("ALPHA_MODEL", "alpha-model")
    monkeypatch.setenv("BETA_API_KEY", "beta-key")
    monkeypatch.setenv("BETA_BASE_URL", "https://beta.example/v1")
    monkeypatch.setenv("BETA_MODEL", "beta-model")


def test_roles_can_share_one_default_model(monkeypatch):
    _configure(monkeypatch)

    for role in ("planner", "architect", "developer", "tester", "reviewer"):
        assert model_config.resolve_role_llm_spec(role) == ("alpha", "alpha-model")


def test_roles_can_override_provider_and_model(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("REVIEWER_PROVIDER", "beta")
    monkeypatch.setenv("REVIEWER_MODEL", "beta-reviewer")

    assert model_config.resolve_role_llm_spec("reviewer") == ("beta", "beta-reviewer")
    assert model_config.resolve_role_llm_spec("developer") == ("alpha", "alpha-model")


def test_developers_can_each_override_model(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("DEVELOPER_COUNT", "3")
    monkeypatch.setenv("DEVELOPER_1_PROVIDER", "alpha")
    monkeypatch.setenv("DEVELOPER_1_MODEL", "alpha-dev")
    monkeypatch.setenv("DEVELOPER_2_PROVIDER", "beta")
    monkeypatch.setenv("DEVELOPER_2_MODEL", "beta-dev")
    monkeypatch.setenv("DEVELOPER_3_PROVIDER", "alpha")
    monkeypatch.setenv("DEVELOPER_3_MODEL", "alpha-fast-dev")

    assert model_config.get_developer_count() == 3
    assert model_config.resolve_developer_llm_spec(1) == ("alpha", "alpha-dev")
    assert model_config.resolve_developer_llm_spec(2) == ("beta", "beta-dev")
    assert model_config.resolve_developer_llm_spec(3) == ("alpha", "alpha-fast-dev")


def test_missing_model_is_rejected(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.delenv("ALPHA_MODEL")
    monkeypatch.delenv("DEFAULT_MODEL")

    with pytest.raises(ValueError, match="No model configured"):
        model_config.resolve_role_llm_spec("planner")
