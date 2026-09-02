from __future__ import annotations

import logging
import sys
from typing import Any

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.workspace import MCPWorkspaceBoundary
from mcp_bridge.workspace_mutation import MCPWorkspaceMutationBoundary, WorkspaceMutationEvent


LOGGER = logging.getLogger("ai_team.mcp_bridge")


def _configure_logging(level: str) -> None:
    # MCP stdio uses stdout as the protocol wire. Keep application logs on stderr.
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def create_server(config: MCPBridgeConfig | None = None) -> Any:
    """Create the Phase 4 secure workspace mutation MCP server."""
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError(
            "MCP SDK is not installed. Run: python -m pip install -r requirements-mcp.txt"
        ) from exc

    effective_config = config or MCPBridgeConfig.from_env()
    _configure_logging(effective_config.log_level)
    boundary = MCPWorkspaceBoundary(effective_config.workspace_root)
    mutation_events: list[WorkspaceMutationEvent] = []
    mutation_boundary = MCPWorkspaceMutationBoundary(
        effective_config.workspace_root,
        audit_sink=mutation_events.append,
    )

    server = MCPServer(
        "AI-Team Local MCP Bridge",
        instructions=(
            "Local bridge for the authorized AI-Team workspace. "
            "Phase 4 exposes bounded workspace read and mutation tools. "
            "Terminal, network, and direct Git metadata access remain disabled."
        ),
    )

    @server.tool(
        name="bridge_health",
        title="AI-Team MCP Bridge Health",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def bridge_health() -> dict[str, object]:
        """Return bridge status without exposing host-wide filesystem details."""
        return {
            "status": "ok",
            "bridge": "ai-team-local-mcp",
            "phase": "4-secure-workspace-mutation",
            "workspace_configured": True,
            "read_enabled": True,
            "write_enabled": True,
            "terminal_enabled": False,
            "git_write_enabled": False,
        }

    @server.tool(
        name="workspace_validate_path",
        title="Validate AI-Team Workspace Path",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def workspace_validate_path(
        path: str = ".",
        expected_kind: str | None = None,
    ) -> dict[str, object]:
        """Validate an authorized path without returning its host absolute path."""
        resolved = boundary.resolve(
            path,
            require_exists=expected_kind is not None,
            expected_kind=expected_kind,
        )
        return {"authorized": True, "path": resolved.relative_path, "kind": resolved.kind}

    @server.tool(
        name="workspace_list_files",
        title="List AI-Team Workspace Files",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def workspace_list_files(path: str = ".", limit: int = 500) -> list[str]:
        """List bounded authorized workspace files using relative paths."""
        return boundary.list_files(path, limit=limit)

    @server.tool(
        name="workspace_read_file",
        title="Read AI-Team Workspace File",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def workspace_read_file(path: str, max_bytes: int = 512 * 1024) -> str:
        """Read one bounded authorized workspace text file."""
        return boundary.read_file(path, max_bytes=max_bytes)

    @server.tool(
        name="workspace_search_text",
        title="Search AI-Team Workspace Text",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def workspace_search_text(
        query: str,
        path: str = ".",
        max_results: int = 100,
        case_sensitive: bool = False,
    ) -> list[dict[str, object]]:
        """Search bounded authorized text files and return relative matches."""
        return boundary.search_text(
            query,
            path,
            max_results=max_results,
            case_sensitive=case_sensitive,
        )

    @server.tool(
        name="workspace_write_file",
        title="Write AI-Team Workspace File",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False),
    )
    def workspace_write_file(
        path: str,
        content: str,
        max_bytes: int = 512 * 1024,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Create or explicitly overwrite one bounded workspace text file."""
        result = mutation_boundary.write_file(
            path,
            content,
            max_bytes=max_bytes,
            overwrite=overwrite,
        )
        LOGGER.info(
            "workspace mutation operation=%s path=%s bytes=%s",
            result["operation"],
            result["path"],
            result["bytes_written"],
        )
        return result

    @server.tool(
        name="workspace_delete_file",
        title="Delete AI-Team Workspace File",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False),
    )
    def workspace_delete_file(path: str) -> dict[str, object]:
        """Delete one regular file from the authorized workspace."""
        result = mutation_boundary.delete_file(path)
        LOGGER.info("workspace mutation operation=delete path=%s", result["path"])
        return result

    return server


def main() -> None:
    config = MCPBridgeConfig.from_env()
    server = create_server(config)
    server.run()


if __name__ == "__main__":
    main()
