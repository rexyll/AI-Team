from __future__ import annotations

from typing import Any

from mcp_bridge.orchestration import MCPOrchestrationBoundary


def register_orchestration_tools(server: Any, boundary: MCPOrchestrationBoundary) -> None:
    """Register the Phase 6 orchestration tools on a host-owned MCP server."""
    if boundary is None or not isinstance(boundary, MCPOrchestrationBoundary):
        raise TypeError("boundary must be an MCPOrchestrationBoundary")
    if not hasattr(server, "tool"):
        raise TypeError("server must expose tool()")

    try:
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("MCP SDK is not installed") from exc

    @server.tool(name="task_list", title="List AI-Team Tasks", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def task_list() -> list[dict[str, Any]]:
        return boundary.list_tasks()

    @server.tool(name="task_get", title="Get AI-Team Task", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def task_get(task_id: str) -> dict[str, Any]:
        return boundary.get_task(task_id)

    @server.tool(name="task_ready", title="List Ready AI-Team Tasks", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def task_ready() -> list[dict[str, Any]]:
        return boundary.ready_tasks()

    @server.tool(name="agent_list", title="List AI-Team Agents", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def agent_list() -> list[dict[str, Any]]:
        return boundary.agents()

    @server.tool(name="workflow_capabilities", title="AI-Team Workflow Capabilities", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def workflow_capabilities() -> dict[str, bool]:
        return boundary.workflow_capabilities()

    @server.tool(name="task_execute", title="Execute AI-Team Task", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
    def task_execute(task_id: str) -> dict[str, Any]:
        return boundary.execute_task(task_id)
