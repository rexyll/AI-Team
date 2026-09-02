from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import MCPBridgeConfigurationError
from .policy import DEFAULT_POLICY_PROFILE, MCPPolicy, POLICY_PROFILE_ENV


WORKSPACE_ENV = "AI_TEAM_WORKSPACE"
LOG_LEVEL_ENV = "AI_TEAM_MCP_LOG_LEVEL"
TRANSPORT_ENV = "AI_TEAM_MCP_TRANSPORT"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_TRANSPORT = "stdio"
STANDALONE_DEFAULT_POLICY_PROFILE = "readonly"
_ALLOWED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
_ALLOWED_TRANSPORTS = {"stdio"}


@dataclass(frozen=True)
class MCPTransportConfig:
    """Transport settings accepted by the local bridge.

    The local MCP bridge intentionally exposes stdio only. Adding a network
    transport must be a separate security-reviewed capability, not an
    implicit startup option.
    """

    transport: str = DEFAULT_TRANSPORT


@dataclass(frozen=True)
class MCPBridgeConfig:
    """Validated process configuration for the Local MCP Bridge."""

    workspace_root: Path
    log_level: str = DEFAULT_LOG_LEVEL
    policy_profile: str = DEFAULT_POLICY_PROFILE
    transport: MCPTransportConfig = MCPTransportConfig()

    @property
    def policy(self) -> MCPPolicy:
        return MCPPolicy.from_profile(self.policy_profile)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        standalone: bool = False,
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

        raw_transport = env.get(TRANSPORT_ENV, DEFAULT_TRANSPORT).strip().lower()
        if raw_transport not in _ALLOWED_TRANSPORTS:
            raise MCPBridgeConfigurationError(
                f"{TRANSPORT_ENV} must be one of: "
                + ", ".join(sorted(_ALLOWED_TRANSPORTS))
            )

        default_profile = (
            STANDALONE_DEFAULT_POLICY_PROFILE if standalone else DEFAULT_POLICY_PROFILE
        )
        policy_profile = env.get(POLICY_PROFILE_ENV, default_profile).strip().lower()
        try:
            MCPPolicy.from_profile(policy_profile)
        except ValueError as exc:
            raise MCPBridgeConfigurationError(str(exc)) from exc

        return cls(
            workspace_root=workspace_root,
            log_level=log_level,
            policy_profile=policy_profile,
            transport=MCPTransportConfig(transport=raw_transport),
        )
