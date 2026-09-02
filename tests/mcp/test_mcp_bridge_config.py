from pathlib import Path

import pytest

from mcp_bridge.config import (
    LOG_LEVEL_ENV,
    WORKSPACE_ENV,
    MCPBridgeConfig,
)
from mcp_bridge.errors import MCPBridgeConfigurationError


def test_config_requires_explicit_workspace():
    with pytest.raises(MCPBridgeConfigurationError, match=WORKSPACE_ENV):
        MCPBridgeConfig.from_env({})


def test_config_rejects_relative_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(MCPBridgeConfigurationError, match="absolute"):
        MCPBridgeConfig.from_env({WORKSPACE_ENV: "relative/path"})


def test_config_accepts_absolute_existing_directory(tmp_path):
    config = MCPBridgeConfig.from_env(
        {
            WORKSPACE_ENV: str(tmp_path),
            LOG_LEVEL_ENV: "debug",
        }
    )

    assert config.workspace_root == tmp_path.resolve()
    assert config.log_level == "DEBUG"


def test_config_rejects_invalid_log_level(tmp_path):
    with pytest.raises(MCPBridgeConfigurationError, match=LOG_LEVEL_ENV):
        MCPBridgeConfig.from_env(
            {
                WORKSPACE_ENV: str(tmp_path),
                LOG_LEVEL_ENV: "verbose",
            }
        )
