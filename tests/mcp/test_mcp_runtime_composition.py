from __future__ import annotations

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.orchestration import MCPOrchestrationBoundary
from mcp_bridge.server import create_server
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager


@pytest.mark.anyio
async def test_server_exposes_host_composed_orchestration_capabilities(tmp_path):
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
    ])
    router = AgentRouter()

    class Host:
        def __init__(self):
            self.task_manager = manager
            self.agent_router = router
            self.calls = 0

        def _execute_task(self, task):
            self.calls += 1
            task.status = "completed"

    host = Host()
    boundary = MCPOrchestrationBoundary.from_orchestrator(host)
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), orchestration=boundary)

    async with Client(server, raise_exceptions=True) as client:
        health = await client.call_tool("bridge_health", {})
        capabilities = await client.call_tool("workflow_capabilities", {})
        task = await client.call_tool("task_execute", {"task_id": "TASK-001"})

    assert health.structured_content["orchestration_enabled"] is True
    assert health.structured_content["orchestration"]["workflow_execute"] is True
    assert capabilities.structured_content == {
        "task_read": True,
        "agent_read": True,
        "workflow_execute": True,
        "workflow_cancel": False,
    }
    assert task.structured_content["id"] == "TASK-001"
    assert task.structured_content["status"] == "completed"
    assert host.calls == 1
    assert "context" not in task.structured_content
