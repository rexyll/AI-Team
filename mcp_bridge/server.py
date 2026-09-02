from __future__ import annotations

import logging
import sys
from typing import Any

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.git import MCPGitCapabilityBoundary
from mcp_bridge.orchestration import MCPOrchestrationBoundary
from mcp_bridge.orchestration_tools import register_orchestration_tools
from mcp_bridge.terminal import MCPTerminalCapabilityBoundary, MCPTerminalResult
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


def create_server(config: MCPBridgeConfig | None = None, *, orchestration: MCPOrchestrationBoundary | None = None, terminal: bool = False) -> Any:
    """Create the secure MCP server with optional host-owned capabilities."""
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
    terminal_events: list[MCPTerminalResult] = []
    terminal_boundary = MCPTerminalCapabilityBoundary(effective_config.workspace_root, audit_sink=terminal_events.append) if terminal else None

    server = MCPServer("AI-Team Local MCP Bridge", instructions=(
        "Local bridge for the authorized AI-Team workspace. Phase 7 exposes bounded workspace, mutation, "
        "allow-listed Git, optional host-owned task/agent/workflow, and optional controlled terminal capabilities. "
        "Network, and direct Git metadata access remain disabled."
    ))

    @server.tool(name="bridge_health", title="AI-Team MCP Bridge Health", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def bridge_health() -> dict[str, object]:
        capabilities = orchestration.workflow_capabilities() if orchestration is not None else {
            "task_read": False, "agent_read": False, "workflow_execute": False,
            "workflow_cancel": False, "execution_observability": False,
            "execution_status": False, "execution_idempotency": False,
        }
        return {"status": "ok", "bridge": "ai-team-local-mcp", "phase": "7-controlled-terminal-boundary",
                "workspace_configured": True, "read_enabled": True, "write_enabled": True,
                "terminal_enabled": terminal_boundary is not None, "git_enabled": True, "git_write_enabled": True,
                "orchestration_enabled": orchestration is not None, "orchestration": capabilities}

    @server.tool(name="workspace_validate_path", title="Validate AI-Team Workspace Path", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_validate_path(path: str = ".", expected_kind: str | None = None) -> dict[str, object]:
        resolved = boundary.resolve(path, require_exists=expected_kind is not None, expected_kind=expected_kind)
        return {"authorized": True, "path": resolved.relative_path, "kind": resolved.kind}

    @server.tool(name="workspace_list_files", title="List AI-Team Workspace Files", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_list_files(path: str = ".", limit: int = 500) -> list[str]: return boundary.list_files(path, limit=limit)

    @server.tool(name="workspace_read_file", title="Read AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_read_file(path: str, max_bytes: int = 512 * 1024) -> str: return boundary.read_file(path, max_bytes=max_bytes)

    @server.tool(name="workspace_search_text", title="Search AI-Team Workspace Text", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workspace_search_text(query: str, path: str = ".", max_results: int = 100, case_sensitive: bool = False) -> list[dict[str, object]]: return boundary.search_text(query, path, max_results=max_results, case_sensitive=case_sensitive)

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
    def git_status(path: str = ".") -> dict[str, object]: return git_boundary.status(path)
    @server.tool(name="git_diff", title="Git Diff", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_diff(path: str = ".", staged: bool = False) -> dict[str, object]: return git_boundary.diff(path, staged=staged)
    @server.tool(name="git_log", title="Git Log", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_log(path: str = ".", max_count: int = 20) -> dict[str, object]: return git_boundary.log(path, max_count=max_count)
    @server.tool(name="git_show", title="Git Show", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_show(path: str = ".", revision: str = "HEAD") -> dict[str, object]: return git_boundary.show(path, revision=revision)
    @server.tool(name="git_branch", title="Git Branch", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_branch(path: str = ".") -> dict[str, object]: return git_boundary.branch(path)
    @server.tool(name="git_rev_parse", title="Git Rev Parse", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def git_rev_parse(path: str = ".", revision: str = "HEAD") -> dict[str, object]: return git_boundary.rev_parse(path, revision=revision)
    @server.tool(name="git_add", title="Git Add", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def git_add(path: str, paths: list[str]) -> dict[str, object]: return git_boundary.add(path, paths)
    @server.tool(name="git_commit", title="Git Commit", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def git_commit(path: str, message: str) -> dict[str, object]: return git_boundary.commit(path, message)

    if terminal_boundary is not None:
        @server.tool(name="terminal_execute", title="Execute Controlled Development Command", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        def terminal_execute(command: str, cwd: str = ".", timeout: float = 30.0, max_output_chars: int = 64 * 1024) -> dict[str, object]:
            result = terminal_boundary.execute(command, cwd, timeout=timeout, max_output_chars=max_output_chars)
            LOGGER.info("terminal execution id=%s cwd=%s exit_code=%s timed_out=%s truncated=%s", result["execution_id"], result["cwd"], result["exit_code"], result["timed_out"], result["truncated"])
            return result

        @server.tool(name="terminal_execution_status", title="Terminal Execution Status", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
        def terminal_execution_status(execution_id: str) -> dict[str, object]:
            return terminal_boundary.execution_status(execution_id)

        @server.tool(name="terminal_execution_history", title="Terminal Execution History", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
        def terminal_execution_history(limit: int = 50) -> list[dict[str, object]]:
            return terminal_boundary.execution_history(limit=limit)

    if orchestration is not None:
        register_orchestration_tools(server, orchestration)
    return server


def main() -> None:
    create_server(MCPBridgeConfig.from_env()).run()


if __name__ == "__main__":
    main()
