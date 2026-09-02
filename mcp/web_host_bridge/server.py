from __future__ import annotations

import functools
import logging
import sys
from typing import Any, Callable

from .config import MCPBridgeConfig
from .error_contract import normalize_error
from .git import MCPGitCapabilityBoundary
from .observability import MCPOperationTracker
from .orchestration import MCPOrchestrationBoundary
from .orchestration_tools import register_orchestration_tools
from .terminal import MCPTerminalCapabilityBoundary, MCPTerminalResult
from .workspace import MCPWorkspaceBoundary
from .workspace_mutation import MCPWorkspaceMutationBoundary, WorkspaceMutationEvent

LOGGER = logging.getLogger("ai_team.mcp_bridge")


def _configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def _extract_execution_id(value: Any) -> str | None:
    if isinstance(value, dict):
        execution_id = value.get("execution_id")
        if isinstance(execution_id, str) and execution_id:
            return execution_id
        nested = value.get("result")
        if nested is not value:
            return _extract_execution_id(nested)
    return None


def create_server(
    config: MCPBridgeConfig | None = None,
    *,
    orchestration: MCPOrchestrationBoundary | None = None,
    terminal: bool = False,
    operation_tracker: MCPOperationTracker | None = None,
) -> Any:
    """Create the secure MCP server with host-owned capability policy."""
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("MCP SDK is not installed. Run: python -m pip install -r requirements-mcp.txt") from exc

    effective_config = config or MCPBridgeConfig.from_env()
    if effective_config.transport.transport != "stdio":
        raise ValueError(f"unsupported MCP transport: {effective_config.transport.transport}")

    policy = effective_config.policy
    _configure_logging(effective_config.log_level)
    tracker = operation_tracker or MCPOperationTracker()

    def tracked_tool(
        capability: str,
        func: Callable[..., Any] | None = None,
    ) -> Callable[..., Any]:
        if func is None:
            return lambda actual_func: tracked_tool(capability, actual_func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            project_id = kwargs.get("project_id")
            project_id = project_id if isinstance(project_id, str) else None

            record = tracker.start(
                capability,
                policy_profile=policy.profile,
                policy_allowed=True,
                project_id=project_id,
            )

            try:
                result = func(*args, **kwargs)
                execution_id = _extract_execution_id(result)
                tracker.finish(record.operation_id, outcome="success", execution_id=execution_id)
                return result
            except Exception as exc:
                normalized = normalize_error(exc)
                tracker.finish(
                    record.operation_id,
                    outcome="error",
                    error_type=normalized["category"],
                    metadata={"error_type": normalized["type"]},
                )
                raise

        return wrapper

    boundary = MCPWorkspaceBoundary(effective_config.workspace_root)
    mutation_events: list[WorkspaceMutationEvent] = []
    mutation_boundary = MCPWorkspaceMutationBoundary(effective_config.workspace_root, audit_sink=mutation_events.append)
    git_boundary = MCPGitCapabilityBoundary(effective_config.workspace_root)
    terminal_enabled = terminal and policy.allows("terminal")
    terminal_events: list[MCPTerminalResult] = []
    terminal_boundary = (
        MCPTerminalCapabilityBoundary(effective_config.workspace_root, audit_sink=terminal_events.append)
        if terminal_enabled else None
    )

    if terminal and not policy.allows("terminal"):
        LOGGER.warning("terminal capability requested but denied by policy profile=%s", policy.profile)

    server = MCPServer("AI-Team Local MCP Bridge", instructions=(
        "Local bridge for the authorized AI-Team workspace. Phase 7 exposes bounded workspace, mutation, "
        "allow-listed Git, optional host-owned task/agent/workflow, and optional controlled terminal capabilities. "
        "Network, and direct Git metadata access remain disabled. Transport is stdio only."
    ))

    @server.tool(name="bridge_health", title="AI-Team MCP Bridge Health", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("bridge_health")
    def bridge_health() -> dict[str, object]:
        capabilities = orchestration.workflow_capabilities() if orchestration is not None else {
            "task_read": False, "agent_read": False, "workflow_execute": False,
            "workflow_cancel": False, "execution_observability": False,
            "execution_status": False, "execution_idempotency": False,
        }
        if not policy.workflow_execute:
            capabilities = dict(capabilities)
            capabilities["workflow_execute"] = False
        return {
            "status": "ok",
            "bridge": "ai-team-local-mcp",
            "phase": "7-controlled-terminal-boundary",
            "workspace_configured": True,
            "policy_profile": policy.profile,
            "transport": effective_config.transport.transport,
            "read_enabled": True,
            "write_enabled": policy.workspace_write,
            "terminal_enabled": terminal_boundary is not None,
            "git_enabled": True,
            "git_write_enabled": policy.git_write,
            "orchestration_enabled": orchestration is not None,
            "orchestration": capabilities,
        }

    @server.tool(name="bridge_readiness", title="AI-Team MCP Bridge Readiness", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("bridge_readiness")
    def bridge_readiness() -> dict[str, object]:
        checks = {
            "workspace": effective_config.workspace_root.is_dir(),
            "policy": policy.profile in {"readonly", "developer", "production"},
            "transport": effective_config.transport.transport == "stdio",
        }
        ready = all(checks.values())
        return {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "checks": checks,
            "policy_profile": policy.profile,
            "transport": effective_config.transport.transport,
        }

    @server.tool(name="workspace_validate_path", title="Validate AI-Team Workspace Path", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("workspace_validate_path")
    def workspace_validate_path(path: str = ".", expected_kind: str | None = None) -> dict[str, object]:
        resolved = boundary.resolve(path, require_exists=expected_kind is not None, expected_kind=expected_kind)
        return {"authorized": True, "path": resolved.relative_path, "kind": resolved.kind}

    @server.tool(name="workspace_list_files", title="List AI-Team Workspace Files", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("workspace_list_files")
    def workspace_list_files(path: str = ".", limit: int = 500) -> list[str]:
        return boundary.list_files(path, limit=limit)

    @server.tool(name="workspace_read_file", title="Read AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("workspace_read_file")
    def workspace_read_file(path: str, max_bytes: int = 512 * 1024) -> str:
        return boundary.read_file(path, max_bytes=max_bytes)

    @server.tool(name="workspace_stat_path", title="Stat AI-Team Workspace Path", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("workspace_stat_path")
    def workspace_stat_path(path: str = ".") -> dict[str, object]:
        return boundary.stat_path(path)

    @server.tool(name="workspace_search_text", title="Search AI-Team Workspace Text", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("workspace_search_text")
    def workspace_search_text(query: str, path: str = ".", max_results: int = 100, case_sensitive: bool = False) -> list[dict[str, object]]:
        return boundary.search_text(query, path, max_results=max_results, case_sensitive=case_sensitive)

    if policy.workspace_write:
        @server.tool(name="workspace_write_file", title="Write AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        @tracked_tool("workspace_write_file")
        def workspace_write_file(path: str, content: str, max_bytes: int = 512 * 1024, overwrite: bool = False) -> dict[str, object]:
            result = mutation_boundary.write_file(path, content, max_bytes=max_bytes, overwrite=overwrite)
            LOGGER.info("workspace mutation operation=%s path=%s bytes=%s", result["operation"], result["path"], result["bytes_written"])
            return result

        @server.tool(name="workspace_delete_file", title="Delete AI-Team Workspace File", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        @tracked_tool("workspace_delete_file")
        def workspace_delete_file(path: str) -> dict[str, object]:
            result = mutation_boundary.delete_file(path)
            LOGGER.info("workspace mutation operation=delete path=%s", result["path"])
            return result

    @server.tool(name="git_status", title="Git Status", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("git_status")
    def git_status(path: str = ".") -> dict[str, object]:
        return git_boundary.status(path)

    @server.tool(name="git_diff", title="Git Diff", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("git_diff")
    def git_diff(path: str = ".", staged: bool = False) -> dict[str, object]:
        return git_boundary.diff(path, staged=staged)

    @server.tool(name="git_log", title="Git Log", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("git_log")
    def git_log(path: str = ".", max_count: int = 20) -> dict[str, object]:
        return git_boundary.log(path, max_count=max_count)

    @server.tool(name="git_show", title="Git Show", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("git_show")
    def git_show(path: str = ".", revision: str = "HEAD") -> dict[str, object]:
        return git_boundary.show(path, revision=revision)

    @server.tool(name="git_branch", title="Git Branch", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("git_branch")
    def git_branch(path: str = ".") -> dict[str, object]:
        return git_boundary.branch(path)

    @server.tool(name="git_rev_parse", title="Git Rev Parse", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked_tool("git_rev_parse")
    def git_rev_parse(path: str = ".", revision: str = "HEAD") -> dict[str, object]:
        return git_boundary.rev_parse(path, revision=revision)

    if policy.git_write:
        @server.tool(name="git_add", title="Git Add", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        @tracked_tool("git_add")
        def git_add(path: str, paths: list[str]) -> dict[str, object]:
            return git_boundary.add(path, paths)

        @server.tool(name="git_commit", title="Git Commit", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        @tracked_tool("git_commit")
        def git_commit(path: str, message: str) -> dict[str, object]:
            return git_boundary.commit(path, message)

    if terminal_boundary is not None:
        @server.tool(name="terminal_execute", title="Execute Controlled Development Command", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        @tracked_tool("terminal_execute")
        def terminal_execute(command: str, cwd: str = ".", timeout: float = 30.0, max_output_chars: int = 64 * 1024) -> dict[str, object]:
            result = terminal_boundary.execute(command, cwd, timeout=timeout, max_output_chars=max_output_chars, include_execution_id=True)
            LOGGER.info("terminal execution id=%s cwd=%s exit_code=%s timed_out=%s truncated=%s", result["execution_id"], result["cwd"], result["exit_code"], result["timed_out"], result["truncated"])
            return {"result": result}

        @server.tool(name="terminal_execution_status", title="Terminal Execution Status", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
        @tracked_tool("terminal_execution_status")
        def terminal_execution_status(execution_id: str) -> dict[str, object]:
            return {"result": terminal_boundary.execution_status(execution_id)}

        @server.tool(name="terminal_execution_history", title="Terminal Execution History", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
        @tracked_tool("terminal_execution_history")
        def terminal_execution_history(limit: int = 50) -> dict[str, object]:
            return {"result": terminal_boundary.execution_history(limit=limit)}

    if orchestration is not None:
        register_orchestration_tools(
            server,
            orchestration,
            allow_execute=policy.workflow_execute,
            operation_tracker=tracker,
            policy_profile=policy.profile,
        )
    return server


def main() -> None:
    create_server(MCPBridgeConfig.from_env(standalone=True)).run()


if __name__ == "__main__":
    main()
