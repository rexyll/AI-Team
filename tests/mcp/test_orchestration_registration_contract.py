from __future__ import annotations

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.orchestration import MCPOrchestrationBoundary
from mcp_bridge.orchestration_tools import register_orchestration_tools


def _boundary(tmp_path):
    from runtime.task_manager import TaskManager

    return MCPOrchestrationBoundary(TaskManager([]))


@pytest.mark.anyio
async def test_orchestration_tools_work_without_optional_tracker(tmp_path) -> None:
    from mcp.server import MCPServer

    server = MCPServer("test")
    register_orchestration_tools(server, _boundary(tmp_path), operation_tracker=None)

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()

    names = {tool.name for tool in result.tools}
    assert "task_list" in names
    assert "task_get" in names
    assert "task_execute" in names
