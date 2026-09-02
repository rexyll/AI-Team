from __future__ import annotations

import logging
import sys
from typing import Any

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.workspace import MCPWorkspaceBoundary


LOGGER = logging.getLogger("ai_team.mcp_bridge")


def _configure_logging(level: str) -> None:
    # MCP stdio uses stdout as the protocol wire. Keep application logs on stderr.
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)

    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def create_server(config: MCPBridgeConfig | None = None) -> Any:
    """Create the Phase 0-2 MCP server.

    MCP SDK imports are intentionally local so importing the bridge's config or
    path-security modules does not require the optional MCP dependency.
    """
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError(
            'MCP SDK is not installed. Run: python -m pip install -r requirements-mcp.txt'
        ) from exc

    effective_config = config or MCPBridgeConfig.from_env()
    _configure_logging(effective_config.log_level)
    boundary = MCPWorkspaceBoundary(effective_config.workspace_root)

    server = MCPServer(
        "AI-Team Local MCP Bridge",
        instructions=(
            "Local bridge for the authorized AI-Team workspace. "
            "Phase 0-2 exposes diagnostics only; source read/search/write tools "
            "are added in later planned phases."
        ),
    )

    @server.tool(
        name="bridge_health",
        title="AI-Team MCP Bridge Health",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    def bridge_health() -> dict[str, object]:
        """Return bridge status without exposing host-wide filesystem details."""
        return {
            "status": "ok",
            "bridge": "ai-team-local-mcp",
            "phase": "0-2",
            "workspace_configured": True,
            "write_enabled": False,
            "terminal_enabled": False,
            "git_write_enabled": False,
        }

    @server.tool(
        name="workspace_validate_path",
        title="Validate AI-Team Workspace Path",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    def workspace_validate_path(
        path: str = ".",
        expected_kind: str | None = None,
    ) -> dict[str, object]:
        """Validate that a path is authorized without returning its host absolute path."""
        resolved = boundary.resolve(
            path,
            require_exists=expected_kind is not None,
            expected_kind=expected_kind,
        )
        return {
            "authorized": True,
            "path": resolved.relative_path,
            "kind": resolved.kind,
        }

    return server


def main() -> None:
    config = MCPBridgeConfig.from_env()
    server = create_server(config)
    # In MCP Python SDK v2, run() defaults to stdio.
    server.run()


if __name__ == "__main__":
    main()
