from __future__ import annotations

import pytest

from web_host_bridge.config import (
    MCPBridgeConfig,
    MCPTransportConfig,
    TRANSPORT_ENV,
    WORKSPACE_ENV,
)
from web_host_bridge.errors import MCPBridgeConfigurationError


def test_standalone_config_defaults_to_readonly(tmp_path) -> None:
    config = MCPBridgeConfig.from_env(
        {WORKSPACE_ENV: str(tmp_path)},
        standalone=True,
    )

    assert config.policy_profile == "readonly"
    assert config.policy.workspace_write is False
    assert config.policy.git_write is False
    assert config.policy.terminal is False
    assert config.policy.workflow_execute is False


def test_standalone_explicit_developer_profile_is_allowed(tmp_path) -> None:
    config = MCPBridgeConfig.from_env(
        {WORKSPACE_ENV: str(tmp_path), "AI_TEAM_MCP_POLICY_PROFILE": "developer"},
        standalone=True,
    )

    assert config.policy_profile == "developer"
    assert config.policy.workflow_execute is True


def test_standalone_transport_is_stdio_by_default(tmp_path) -> None:
    config = MCPBridgeConfig.from_env({WORKSPACE_ENV: str(tmp_path)}, standalone=True)

    assert config.transport.transport == "stdio"


def test_transport_rejects_unknown_value(tmp_path) -> None:
    with pytest.raises(MCPBridgeConfigurationError, match="transport"):
        MCPBridgeConfig.from_env(
            {WORKSPACE_ENV: str(tmp_path), TRANSPORT_ENV: "http"},
            standalone=True,
        )


def test_transport_config_is_explicitly_stdio_only() -> None:
    config = MCPTransportConfig()
    assert config.transport == "stdio"
