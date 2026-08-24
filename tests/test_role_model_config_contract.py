"""Multi-provider, per-role model binding contracts.

Each team role resolves to a ``(provider_profile, model_id)`` pair from
the environment; the agent factory injects one ProviderLLM per role from
those bindings. Resolution must be dynamic (read at call time) so tests
and runtime switching work without re-importing modules.
"""

from __future__ import annotations

import pytest

from config.model import (
    get_client_for,
    get_provider_profile,
    resolve_role_llm_spec,
)
from runtime.agent_factory import create_agent_router


SUPPORTED = ("planner", "architect", "developer", "tester", "reviewer")


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


def test_default_profile_is_agnes(monkeypatch) -> None:
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)

    profile = get_provider_profile()

    assert profile.name == "agnes"
    assert profile.default_model == "agnes-2.5-flash"


def test_openrouter_profile_defaults_to_ox_alpha(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    # 用户 .env 可能自带 BASE_URL 覆盖；本用例只验证内置回退值。
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    profile = get_provider_profile("openrouter")

    assert profile.name == "openrouter"
    assert profile.default_model == "stealth/ox-alpha"
    assert profile.default_base_url == "https://openrouter.ai/api/v1"


def test_unknown_provider_profile_raises() -> None:
    with pytest.raises(ValueError):
        get_provider_profile("does-not-exist")


def test_base_url_override_is_honored(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://mirror.example/v1")

    assert "mirror.example" in get_provider_profile("openrouter").default_base_url


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


def test_every_supported_role_resolves_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DEFAULT_PROVIDER", raising=False)

    for role in SUPPORTED:
        provider_name, model = resolve_role_llm_spec(role)
        assert provider_name == "agnes"
        assert model  # non-empty model id


def test_role_env_overrides_bind_per_role(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_PROVIDER", "openrouter")
    for role in SUPPORTED:
        monkeypatch.setenv(f"{role.upper()}_MODEL", f"m-{role}")
    # 仅覆盖 developer 的 provider，其余仍走全局默认。
    monkeypatch.setenv("DEVELOPER_PROVIDER", "agnes")

    planner_provider, planner_model = resolve_role_llm_spec("planner")
    dev_provider, dev_model = resolve_role_llm_spec("developer")

    assert planner_provider == "openrouter"
    assert planner_model == "m-planner"
    assert dev_provider == "agnes"
    assert dev_model == "m-developer"


def test_unknown_role_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_role_llm_spec("ceo")


# ---------------------------------------------------------------------------
# Lazy client cache
# ---------------------------------------------------------------------------


def test_client_cache_is_per_profile(monkeypatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "dummy-agnes")
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-or")

    first = get_client_for("openrouter")
    second = get_client_for("openrouter")
    agnes = get_client_for("agnes")

    assert first is second          # 同 profile 复用缓存
    assert first is not agnes       # 不同 profile 各自独立


def test_missing_credential_fails_lazily_per_profile(
    monkeypatch,
) -> None:
    from config.model import _CLIENTS

    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")
    get_client_for("openrouter")  # 预热缓存

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _CLIENTS.pop("openrouter", None)  # 绕过缓存直击凭据守卫
    try:
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            get_client_for("openrouter")
    finally:
        _CLIENTS.pop("openrouter", None)  # 不给其他用例留下脏缓存


# ---------------------------------------------------------------------------
# Factory wiring (imports the full agent chain)
# ---------------------------------------------------------------------------


def test_factory_binds_role_models_into_agents(monkeypatch) -> None:
    from runtime.llm.provider import ProviderLLM

    monkeypatch.setenv("DEFAULT_PROVIDER", "openrouter")
    monkeypatch.setenv("PLANNER_MODEL", "planner-x")
    monkeypatch.setenv("TESTER_MODEL", "tester-y")

    router = create_agent_router()

    planner_llm = router.get_agent("planner").llm
    tester_llm = router.get_agent("tester").llm
    developer_llm = router.get_agent("developer").llm

    assert isinstance(planner_llm, ProviderLLM)
    assert planner_llm.model == "planner-x"
    assert planner_llm.provider_profile == "openrouter"
    assert tester_llm.model == "tester-y"
    # 未显式覆盖的角色使用该 provider 的默认模型。
    assert developer_llm.model == "stealth/ox-alpha"
