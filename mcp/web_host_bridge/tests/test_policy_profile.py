from __future__ import annotations

import pytest

from web_host_bridge.config import MCPBridgeConfig, WORKSPACE_ENV
from web_host_bridge.errors import MCPBridgeConfigurationError
from web_host_bridge.policy import MCPPolicy, POLICY_PROFILE_ENV


def test_developer_policy_preserves_existing_capabilities() -> None:
    policy = MCPPolicy.from_profile("developer")

    assert policy.profile == "developer"
    assert policy.workspace_write is True
    assert policy.git_write is True
    assert policy.terminal is True
    assert policy.workflow_execute is True


def test_readonly_policy_disables_mutating_and_execution_capabilities() -> None:
    policy = MCPPolicy.from_profile("readonly")

    assert policy.workspace_write is False
    assert policy.git_write is False
    assert policy.terminal is False
    assert policy.workflow_execute is False


def test_production_policy_is_fail_closed() -> None:
    policy = MCPPolicy.from_profile("production")

    assert policy.profile == "production"
    assert policy.workspace_write is False
    assert policy.git_write is False
    assert policy.terminal is False
    assert policy.workflow_execute is False


def test_unknown_policy_capability_is_rejected() -> None:
    policy = MCPPolicy.from_profile("readonly")

    with pytest.raises(ValueError, match="unknown MCP capability"):
        policy.allows("not_a_capability")


def test_config_loads_policy_profile(tmp_path) -> None:
    config = MCPBridgeConfig.from_env({
        WORKSPACE_ENV: str(tmp_path),
        POLICY_PROFILE_ENV: "readonly",
    })

    assert config.policy_profile == "readonly"
    assert config.policy.workspace_write is False


def test_config_loads_production_policy_profile(tmp_path) -> None:
    config = MCPBridgeConfig.from_env({
        WORKSPACE_ENV: str(tmp_path),
        POLICY_PROFILE_ENV: "production",
    })

    assert config.policy_profile == "production"
    assert config.policy.workspace_write is False
    assert config.policy.git_write is False
    assert config.policy.terminal is False
    assert config.policy.workflow_execute is False


def test_config_rejects_unknown_policy_profile(tmp_path) -> None:
    with pytest.raises(MCPBridgeConfigurationError, match="policy profile"):
        MCPBridgeConfig.from_env({
            WORKSPACE_ENV: str(tmp_path),
            POLICY_PROFILE_ENV: "unknown",
        })
