from __future__ import annotations

import logging
import sys
from typing import Any

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.git import MCPGitCapabilityBoundary
from mcp_bridge.workspace import MCPWorkspaceBoundary
from mcp_bridge.workspace_mutation import MCPWorkspaceMutationBoundary, WorkspaceMutationEvent

LOGGER = logging.getLogger("ai_team.mcp_bridge")


def _configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def create_server(config: MCPBridgeConfig | None = None) -> Any:
    """Create the Phase 5 secure workspace and Git MCP server."""
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("MCP SDK is not installed. Run: python -m pip install -r requirements-mcp.txt") from exc

    effective_config = config or MCPBridgeConfig.from_env()
    _configure_logging(effective_config.log_level)
    boundary = MCPWorkspaceBoundary(effective_config.workspace_root)
    mutation_events: list[WorkspaceMutationEvent] = []
    mutation_boundary = MCPWorkspaceMutationBoundary(effective_config.workspace_root, audit_sink=mutation_events.append)
    git_boundary = MCPGitCapabilityBoundary(effective_config.workspace_root)

    server = MCPServer(
        "AI-Team Local MCP Bridge",
        instructions=(
            "Local bridge for the authorized AI-Team workspace. Phase 5 exposes bounded workspace read, "
            "mutation, and allow-listed Git tools. Terminal, network, and direct Git metadata access remain disabled."
        ),
    )

    @server.tool(name="bridge_health", title="AI-Team MCP Bridge Health", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def bridge_health() -> dict[str, object]:
        return {"status": "ok", "bridge": "ai-team-local-mcp", "phase": "5-git-capability-boundary", "workspace_configured": True, "read_enabled": True, "write_enabled": True, "terminal_enabled": False, "git_enabled": True, "git_write_enabled": True}

    @server.tool(name="workspace_validate_path", title="Validate AI-Team Workspace Path", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_validate_path(path: str = ".", expected_kind: str | None = None) -> dict[str, object]:
        resolved = boundary.resolve(path, require_exists=expected_kind is not None, expected_kind=expected_kind)
        return {"authorized": True, "path": resolved.relative_path, "kind": resolved.kind}

    @server.tool(name="workspace_list_files", title="List AI-Team Workspace Files", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_list_files(path: str = ".", limit: int = 500) -> list[str]:
        return boundary.list_files(path, limit=limit)

    @server.tool(name="workspace_read_file", title="Read AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_read_file(path: str, max_bytes: int = 512 * 1024) -> str:
        return boundary.read_file(path, max_bytes=max_bytes)

    @server.tool(name="workspace_search_text", title="Search AI-Team Workspace Text", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_search_text(query: str, path: str = ".", max_results: int = 100, case_sensitive: bool = False) -> list[dict[str, object]]:
        return boundary.search_text(query, path, max_results=max_results, case_sensitive=case_sensitive)

    @server.tool(name="workspace_write_file", title="Write AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def workspace_write_file(path: str, content: str, max_bytes: int = 512 * 1024, overwrite: bool = False) -> dict[str, object]:
        result = mutation_boundary.write_file(path, content, max_bytes=max_bytes, overwrite=overwrite)
        LOGGER.info("workspace mutation operation=%s path=%s bytes=%s", result["operation"], result["path"], result["bytes_written"])
        return result

    @server.tool(name="workspace_delete_file", title="Delete AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def workspace_delete_file(path: str) -> dict[str, object]:
        result = mutation_boundary.delete_file(path)
        LOGGER.info("workspace mutation operation=delete path=%s", result["path"])
        return result

    @server.tool(name="git_status", title="Git Status", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_status(path: str = ".") -> dict[str, object]:
        return git_boundary.status(path)

    @server.tool(name="git_diff", title="Git Diff", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_diff(path: str = ".", staged: bool = False) -> dict[str, object]:
        return git_boundary.diff(path, staged=staged)

    @server.tool(name="git_log", title="Git Log", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_log(path: str = ".", max_count: int = 20) -> dict[str, object]:
        return git_boundary.log(path, max_count=max_count)

    @server.tool(name="git_show", title="Git Show", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_show(path: str = ".", revision: str = "HEAD") -> dict[str, object]:
        return git_boundary.show(path, revision=revision)

    @server.tool(name="git_branch", title="Git Branch", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_branch(path: str = ".") -> dict[str, object]:
        return git_boundary.branch(path)

    @server.tool(name="git_rev_parse", title="Git Rev Parse", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_rev_parse(path: str = ".", revision: str = "HEAD") -> dict[str, object]:
        return git_boundary.rev_parse(path, revision=revision)

    @server.tool(name="git_add", title="Git Add", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def git_add(path: str, paths: list[str]) -> dict[str, object]:
        result = git_boundary.add(path, paths)
        LOGGER.info("git mutation operation=add workspace=%s", path)
        return result

    @server.tool(name="git_commit", title="Git Commit", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def git_commit(path: str, message: str) -> dict[str, object]:
        result = git_boundary.commit(path, message)
        LOGGER.info("git mutation operation=commit workspace=%s", path)
        return result

    return server


def main() -> None:
    config = MCPBridgeConfig.from_env()
    server = create_server(config)
    server.run()


if __name__ == "__main__":
    main()
