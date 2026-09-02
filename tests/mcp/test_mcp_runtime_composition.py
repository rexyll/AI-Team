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
from runtime.workflow_event_log import WorkflowEventLog


@pytest.mark.anyio
async def test_server_exposes_host_composed_orchestration_capabilities(tmp_path):
    manager = TaskManager([Task(id="TASK-001", title="First", description="first", role="developer")])
    router = AgentRouter()
    event_log = WorkflowEventLog()

    class Host:
        def __init__(self):
            self.task_manager = manager
            self.agent_router = router
            self.workflow_event_log = event_log
            self.project_id = "PROJECT-001"
            self.calls = 0

        def execute_task(self, task_id: str, *, execution_id: str):
            self.calls += 1
            task = self.task_manager.get_task(task_id)
            task.status = "completed"
            task.context["execution_id"] = execution_id
            return task

    host = Host()
    boundary = MCPOrchestrationBoundary.from_orchestrator(host)
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), orchestration=boundary)

    async with Client(server, raise_exceptions=True) as client:
        health = await client.call_tool("bridge_health", {})
        capabilities = await client.call_tool("workflow_capabilities", {})
        task = await client.call_tool("task_execute", {"task_id": "TASK-001"})
        history = await client.call_tool("task_execution_history", {"task_id": "TASK-001"})

    assert health.structured_content["orchestration_enabled"] is True
    assert health.structured_content["orchestration"]["workflow_execute"] is True
    assert health.structured_content["orchestration"]["execution_observability"] is True
    assert capabilities.structured_content == {
        "task_read": True,
        "agent_read": True,
        "workflow_execute": True,
        "workflow_cancel": False,
        "execution_observability": True,
        "execution_status": True,
        "execution_idempotency": True,
    }
    assert task.structured_content["id"] == "TASK-001"
    assert task.structured_content["status"] == "completed"
    assert task.structured_content["execution_id"]
    assert host.calls == 1
    assert "context" not in task.structured_content
    events = history.structured_content["result"]
    assert [event["event_type"] for event in events] == ["mcp_task_execution_requested", "mcp_task_execution_completed"]
    assert events[0]["execution_id"] == task.structured_content["execution_id"]
    assert events[1]["execution_id"] == task.structured_content["execution_id"]
