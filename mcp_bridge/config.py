from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import MCPBridgeConfigurationError


WORKSPACE_ENV = "AI_TEAM_WORKSPACE"
LOG_LEVEL_ENV = "AI_TEAM_MCP_LOG_LEVEL"
DEFAULT_LOG_LEVEL = "INFO"
_ALLOWED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


@dataclass(frozen=True)
class MCPBridgeConfig:
    """Validated process configuration for the Local MCP Bridge."""

    workspace_root: Path
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "MCPBridgeConfig":
        env = os.environ if environ is None else environ

        raw_workspace = env.get(WORKSPACE_ENV, "").strip()
        if not raw_workspace:
            raise MCPBridgeConfigurationError(
                f"{WORKSPACE_ENV} must be set to the AI-Team repository root"
            )

        raw_path = Path(raw_workspace).expanduser()
        if not raw_path.is_absolute():
            raise MCPBridgeConfigurationError(
                f"{WORKSPACE_ENV} must be an absolute path"
            )

        workspace_root = raw_path.resolve()
        if not workspace_root.exists():
            raise MCPBridgeConfigurationError(
                f"{WORKSPACE_ENV} does not exist: {workspace_root}"
            )
        if not workspace_root.is_dir():
            raise MCPBridgeConfigurationError(
                f"{WORKSPACE_ENV} is not a directory: {workspace_root}"
            )

        log_level = env.get(LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL).strip().upper()
        if log_level not in _ALLOWED_LOG_LEVELS:
            raise MCPBridgeConfigurationError(
                f"{LOG_LEVEL_ENV} must be one of: "
                + ", ".join(sorted(_ALLOWED_LOG_LEVELS))
            )

        return cls(
            workspace_root=workspace_root,
            log_level=log_level,
        )
