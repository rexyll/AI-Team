"""Multi-provider, per-role model binding contracts (pure env-driven).

代码中不存在任何 provider/base_url/model 字面量——一切由环境声明。
每个用例通过 ``scrub_llm_env`` 夹具完全控制自身相关的环境切片（hermetic），
既不依赖用户真实 `.env` 的具体取值，也不会被其污染。
"""

from __future__ import annotations

import pytest

from config.model import (
    declared_provider_names,
    get_client_for,
    get_provider_profile,
    resolve_role_llm_spec,
)
from runtime.agent_factory import create_agent_router


SUPPORTED = ("planner", "architect", "developer", "tester", "reviewer")

_LLM_ENV_VARS = (
    "LLM_PROVIDERS",
    "DEFAULT_PROVIDER",
    "AGNES_API_KEY",
    "AGNES_BASE_URL",
    "AGNES_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
)

# 角色级绑定变量也须清空，否则真实 .env 的 DEVELOPER_MODEL 等会泄漏进用例。
_ROLE_ENV_VARS = tuple(
    f"{role.upper()}_{suffix}"
    for role in SUPPORTED
    for suffix in ("PROVIDER", "MODEL")
)


@pytest.fixture
def clean_llm_env(monkeypatch):
    """清空全部 LLM 相关环境变量——每个用例自行声明所需切片。"""
    for var in _LLM_ENV_VARS + _ROLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _declare(monkeypatch, *, providers=None, default=None, **overrides):
    """便捷封装：声明 provider 列表与逐角色绑定。"""
    if providers is not None:
        monkeypatch.setenv("LLM_PROVIDERS", providers)
    if default is not None:
        monkeypatch.setenv("DEFAULT_PROVIDER", default)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


# ---------------------------------------------------------------------------
# 声明与发现
# ---------------------------------------------------------------------------


def test_zero_config_has_no_providers(clean_llm_env) -> None:
    assert declared_provider_names() == []


def test_builtin_names_require_env_values(clean_llm_env) -> None:
    """agnes/openrouter/deepseek 名字保留但不再内置任何端点：
    未提供 BASE_URL 时必须给出指名指引而非静默回退。"""
    with pytest.raises(ValueError, match="DEEPSEEK_BASE_URL"):
        get_provider_profile("deepseek")


def test_llm_providers_declaration_registers_names(clean_llm_env) -> None:
    _declare(clean_llm_env, providers="moonshot,zhipu")

    assert declared_provider_names()[:2] == ["moonshot", "zhipu"]


def test_api_key_auto_discovery_registers_names(clean_llm_env) -> None:
    clean_llm_env.setenv("MOONSHOT_API_KEY", "sk-x")

    names = declared_provider_names()

    assert "moonshot" in names


# ---------------------------------------------------------------------------
# Profile 解析
# ---------------------------------------------------------------------------


def test_profile_resolves_from_full_triple(clean_llm_env) -> None:
    clean_llm_env.setenv("DEFAULT_PROVIDER", "openrouter")
    clean_llm_env.setenv("OPENROUTER_API_KEY", "k")
    clean_llm_env.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    clean_llm_env.setenv("OPENROUTER_MODEL", "stealth/ox-alpha")

    profile = get_provider_profile("openrouter")

    assert profile.name == "openrouter"
    assert profile.default_base_url == "https://openrouter.ai/api/v1"
    assert profile.default_model == "stealth/ox-alpha"


def test_unknown_profile_without_base_url_raises_with_guidance(clean_llm_env) -> None:
    clean_llm_env.setenv("NOPE_API_KEY", "k")  # 有密钥无端点仍须显式声明端点

    with pytest.raises(ValueError, match="NOPE_BASE_URL"):
        get_provider_profile("nope")


def test_undeclared_profile_requires_explicit_base_url(clean_llm_env) -> None:
    """纯环境语义：有密钥但未声明端点时给出指名指引；补齐后立即可解析。"""
    clean_llm_env.setenv("DEEPSEEK_API_KEY", "k")

    with pytest.raises(ValueError, match="DEEPSEEK_BASE_URL"):
        get_provider_profile("deepseek")

    clean_llm_env.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    profile = get_provider_profile("deepseek")
    assert "api.deepseek.com" in profile.default_base_url
    assert profile.default_model == ""  # 未设 MODEL 时为空串（由角色绑定提供）


def test_base_url_env_overrides_builtin_fallback(clean_llm_env) -> None:
    clean_llm_env.setenv("OPENROUTER_BASE_URL", "https://mirror.example/v1")

    profile = get_provider_profile("openrouter")

    assert profile.default_base_url == "https://mirror.example/v1"


# ---------------------------------------------------------------------------
# 角色解析
# ---------------------------------------------------------------------------


def test_roles_resolve_against_declared_providers(clean_llm_env) -> None:
    _declare(
        clean_llm_env,
        providers="openrouter,deepseek",
        default="openrouter",
        OPENROUTER_API_KEY="k-or",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        OPENROUTER_MODEL="stealth/ox-alpha",
        DEEPSEEK_API_KEY="sk-ds",
        DEEPSEEK_BASE_URL="https://api.deepseek.com",
        DEEPSEEK_MODEL="deepseek-v4-flash",
        PLANNER_PROVIDER="openrouter",
        PLANNER_MODEL="planner-x",
        DEVELOPER_PROVIDER="deepseek",
        DEVELOPER_MODEL="deepseek-v4-flash",
    )

    assert resolve_role_llm_spec("planner") == ("openrouter", "planner-x")
    assert resolve_role_llm_spec("developer") == ("deepseek", "deepseek-v4-flash")


def test_role_model_env_overrides_profile_default(clean_llm_env) -> None:
    _declare(
        clean_llm_env,
        providers="openrouter",
        default="openrouter",
        OPENROUTER_API_KEY="k",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        OPENROUTER_MODEL="stealth/ox-alpha",
        REVIEWER_MODEL="reviewer-special",
    )

    _, reviewer_model = resolve_role_llm_spec("reviewer")

    assert reviewer_model == "reviewer-special"


def test_unknown_role_rejected(clean_llm_env) -> None:
    with pytest.raises(ValueError, match="Unknown role"):
        resolve_role_llm_spec("ceo")


# ---------------------------------------------------------------------------
# 惰性客户端缓存
# ---------------------------------------------------------------------------


def test_client_cache_is_per_profile(clean_llm_env) -> None:
    _declare(
        clean_llm_env,
        providers="openrouter,deepseek",
        OPENROUTER_API_KEY="dummy-or",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        DEEPSEEK_API_KEY="dummy-ds",
        DEEPSEEK_BASE_URL="https://api.deepseek.com",
    )

    first = get_client_for("openrouter")
    second = get_client_for("openrouter")
    ds = get_client_for("deepseek")

    assert first is second
    assert first is not ds


def test_missing_credential_fails_lazily_per_profile(clean_llm_env) -> None:
    from config.model import _CLIENTS

    _declare(
        clean_llm_env,
        providers="openrouter,deepseek",
        OPENROUTER_API_KEY="dummy",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        DEEPSEEK_API_KEY="dummy-ds",
        DEEPSEEK_BASE_URL="https://api.deepseek.com",
    )
    get_client_for("openrouter")

    clean_llm_env.delenv("OPENROUTER_API_KEY", raising=False)
    _CLIENTS.pop("openrouter", None)  # 绕过缓存直击凭据守卫
    try:
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            get_client_for("openrouter")
    finally:
        _CLIENTS.pop("openrouter", None)  # 不留脏缓存


# ---------------------------------------------------------------------------
# 工厂接线（完整 agent 链）
# ---------------------------------------------------------------------------


def test_factory_binds_role_models_into_agents(
    clean_llm_env,
) -> None:
    from runtime.llm.provider import ProviderLLM

    _declare(
        clean_llm_env,
        providers="openrouter",
        default="openrouter",
        OPENROUTER_API_KEY="k",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        OPENROUTER_MODEL="stealth/ox-alpha",
        PLANNER_MODEL="planner-x",
        TESTER_MODEL="tester-y",
    )

    router = create_agent_router()

    planner_llm = router.get_agent("planner").llm
    tester_llm = router.get_agent("tester").llm
    developer_llm = router.get_agent("developer").llm

    assert isinstance(planner_llm, ProviderLLM)
    assert planner_llm.model == "planner-x"
    assert tester_llm.model == "tester-y"
    # 未显式覆盖的角色使用所属 profile 的默认模型。
    assert developer_llm.model == "stealth/ox-alpha"