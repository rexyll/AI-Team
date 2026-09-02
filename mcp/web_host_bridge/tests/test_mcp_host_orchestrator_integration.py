from __future__ import annotations

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from agents.mock_agents import MockAgent
from core.orchestrator import Orchestrator
from web_host_bridge.config import MCPBridgeConfig
from web_host_bridge.orchestration import MCPOrchestrationBoundary
from web_host_bridge.server import create_server
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog


@pytest.mark.anyio
async def test_mcp_executes_through_real_orchestrator_and_recovers_idempotency(tmp_path):
    manager = TaskManager(
        [Task(id="TASK-001", title="Architecture", description="architecture", role="architect")]
    )
    router = AgentRouter()
    router.register(MockAgent("architect"))
    event_log = WorkflowEventLog()
    host = Orchestrator(
        manager,
        router,
        workflow_event_log=event_log,
        project_id="PROJECT-001",
    )

    boundary = MCPOrchestrationBoundary.from_orchestrator(host)
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), orchestration=boundary)

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "task_execute",
            {"task_id": "TASK-001", "idempotency_key": "mcp-real-host-001"},
        )
        execution_id = result.structured_content["execution_id"]
        status = await client.call_tool(
            "task_execution_status",
            {"execution_id": execution_id},
        )
        operation_history = await client.call_tool(
            "mcp_operation_history",
            {"limit": 10},
        )
        task_execute_operation = next(
            item
            for item in operation_history.structured_content["result"]
            if item["capability"] == "task_execute"
        )
        operation = await client.call_tool(
            "mcp_operation_get",
            {"operation_id": task_execute_operation["operation_id"]},
        )

    assert result.structured_content["id"] == "TASK-001"
    assert result.structured_content["status"] == "completed"
    assert manager.get_task("TASK-001").context["execution_id"] == execution_id
    assert status.structured_content["execution_id"] == execution_id
    assert status.structured_content["status"] == "completed"
    assert task_execute_operation["outcome"] == "success"
    assert task_execute_operation["execution_id"] == execution_id
    assert operation.structured_content["operation_id"] == task_execute_operation["operation_id"]
    assert operation.structured_content["capability"] == "task_execute"

    events = [
        event
        for event in event_log.list_for_project("PROJECT-001")
        if event.payload.get("source") == "mcp"
    ]
    assert [event.event_type for event in events] == [
        "mcp_task_execution_requested",
        "mcp_task_execution_completed",
    ]
    assert all(event.payload["execution_id"] == execution_id for event in events)

    recovered_boundary = MCPOrchestrationBoundary.from_orchestrator(host)
    recovered = recovered_boundary.execute_task(
        "TASK-001", idempotency_key="mcp-real-host-001"
    )
    assert recovered["execution_id"] == execution_id
    assert recovered["status"] == "completed"
