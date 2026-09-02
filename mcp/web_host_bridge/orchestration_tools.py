from __future__ import annotations

import functools
from typing import Any, Callable

from .error_contract import normalize_error
from .errors import MCPBridgePolicyError
from .observability import MCPOperationTracker
from .orchestration import MCPOrchestrationBoundary


def _extract_execution_id(value: Any) -> str | None:
    if isinstance(value, dict):
        execution_id = value.get("execution_id")
        if isinstance(execution_id, str) and execution_id:
            return execution_id

        nested = value.get("result")
        if nested is not value:
            return _extract_execution_id(nested)

    return None


def register_orchestration_tools(
    server: Any,
    boundary: MCPOrchestrationBoundary,
    *,
    allow_execute: bool = True,
    operation_tracker: MCPOperationTracker | None = None,
    policy_profile: str = "developer",
) -> None:
    """Register host-owned orchestration and operation-observability tools."""
    if boundary is None or not isinstance(boundary, MCPOrchestrationBoundary):
        raise TypeError("boundary must be an MCPOrchestrationBoundary")
    if not hasattr(server, "tool"):
        raise TypeError("server must expose tool()")
    try:
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("MCP SDK is not installed") from exc

    def tracked(
        capability: str,
        func: Callable[..., Any] | None = None,
    ) -> Callable[..., Any]:
        if func is None:
            return lambda actual_func: tracked(capability, actual_func)
        if operation_tracker is None:
            return func

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            project_id = kwargs.get("project_id")
            project_id = project_id if isinstance(project_id, str) else None

            record = operation_tracker.start(
                capability,
                policy_profile=policy_profile,
                policy_allowed=True,
                project_id=project_id,
            )

            try:
                result = func(*args, **kwargs)
                execution_id = _extract_execution_id(result)
                operation_tracker.finish(
                    record.operation_id,
                    outcome="success",
                    execution_id=execution_id,
                )
                return result
            except Exception as exc:
                normalized = normalize_error(exc)
                operation_tracker.finish(
                    record.operation_id,
                    outcome="error",
                    error_type=normalized["category"],
                    metadata={"error_type": normalized["type"]},
                )
                raise

        return wrapper

    @server.tool(name="task_list", title="List AI-Team Tasks", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("task_list")
    def task_list() -> list[dict[str, Any]]:
        return boundary.list_tasks()

    @server.tool(name="task_get", title="Get AI-Team Task", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("task_get")
    def task_get(task_id: str) -> dict[str, Any]:
        return boundary.get_task(task_id)

    @server.tool(name="task_ready", title="List Ready AI-Team Tasks", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("task_ready")
    def task_ready() -> list[dict[str, Any]]:
        return boundary.ready_tasks()

    @server.tool(name="agent_list", title="List AI-Team Agents", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("agent_list")
    def agent_list() -> list[dict[str, Any]]:
        return boundary.agents()

    @server.tool(name="workflow_capabilities", title="AI-Team Workflow Capabilities", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("workflow_capabilities")
    def workflow_capabilities() -> dict[str, bool]:
        capabilities = boundary.workflow_capabilities()
        if not allow_execute:
            capabilities = dict(capabilities)
            capabilities["workflow_execute"] = False
        return capabilities

    @server.tool(name="task_execution_history", title="AI-Team Task Execution History", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("task_execution_history")
    def task_execution_history(task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return boundary.execution_history(task_id, limit=limit)

    @server.tool(name="task_execution_status", title="AI-Team Task Execution Status", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    @tracked("task_execution_status")
    def task_execution_status(execution_id: str) -> dict[str, Any]:
        return boundary.execution_status(execution_id)

    if operation_tracker is not None:
        @server.tool(name="mcp_operation_history", title="MCP Operation History", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
        @tracked("mcp_operation_history")
        def mcp_operation_history(limit: int = 50) -> list[dict[str, Any]]:
            return operation_tracker.history(limit=limit)

        @server.tool(name="mcp_operation_get", title="Get MCP Operation", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
        @tracked("mcp_operation_get")
        def mcp_operation_get(operation_id: str) -> dict[str, Any]:
            if not isinstance(operation_id, str) or not operation_id.strip():
                raise ValueError("operation_id must be a non-empty string")
            record = operation_tracker.get(operation_id.strip())
            if record is None:
                raise KeyError(f"unknown MCP operation: {operation_id.strip()}")
            return record.as_dict()

    if allow_execute:
        @server.tool(name="task_execute", title="Execute AI-Team Task", annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))
        @tracked("task_execute")
        def task_execute(task_id: str, idempotency_key: str | None = None) -> dict[str, Any]:
            return boundary.execute_task(task_id, idempotency_key=idempotency_key)
    else:
        def task_execute(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise MCPBridgePolicyError("MCP policy profile does not allow workflow execution")
