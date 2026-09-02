from __future__ import annotations

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from web_host_bridge.config import MCPBridgeConfig
from web_host_bridge.orchestration import MCPOrchestrationBoundary
from web_host_bridge.server import create_server
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog


class _Workflow:
    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    def execute(self, task_id: str, *, execution_id: str):
        task = self._manager.get_task(task_id)
        task.status = "completed"
        return task


def _boundary(tmp_path) -> MCPOrchestrationBoundary:
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
    ])
    return MCPOrchestrationBoundary(
        manager,
        workflow_factory=lambda _: _Workflow(manager),
        workflow_event_log=WorkflowEventLog(),
        project_id="PROJECT-001",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("profile", ["readonly", "production"])
async def test_readonly_profiles_hide_orchestration_execution(tmp_path, profile: str) -> None:
    server = create_server(
        MCPBridgeConfig(workspace_root=tmp_path, policy_profile=profile),
        orchestration=_boundary(tmp_path),
    )

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        health = await client.call_tool("bridge_health", {})
        capabilities = await client.call_tool("workflow_capabilities", {})

    names = {tool.name for tool in result.tools}
    assert "task_execute" not in names
    assert "task_list" in names
    assert health.structured_content["orchestration"]["workflow_execute"] is False
    assert capabilities.structured_content["workflow_execute"] is False


@pytest.mark.anyio
async def test_developer_profile_exposes_host_orchestration_execution(tmp_path) -> None:
    server = create_server(
        MCPBridgeConfig(workspace_root=tmp_path, policy_profile="developer"),
        orchestration=_boundary(tmp_path),
    )

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        capabilities = await client.call_tool("workflow_capabilities", {})
        execution = await client.call_tool(
            "task_execute",
            {"task_id": "TASK-001", "idempotency_key": "request-001"},
        )

    names = {tool.name for tool in result.tools}
    assert "task_execute" in names
    assert capabilities.structured_content["workflow_execute"] is True
    assert execution.is_error is False
    assert execution.structured_content["execution_id"]
