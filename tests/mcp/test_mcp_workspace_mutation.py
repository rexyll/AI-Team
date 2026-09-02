import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.server import create_server


@pytest.mark.anyio
async def test_server_lists_phase_5_tools(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
    assert names == {"bridge_health", "workspace_validate_path", "workspace_list_files", "workspace_read_file", "workspace_search_text", "workspace_write_file", "workspace_delete_file", "git_status", "git_diff", "git_log", "git_show", "git_branch", "git_rev_parse", "git_add", "git_commit"}


@pytest.mark.anyio
async def test_health_reports_phase_7_capability_phase(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("bridge_health", {})

    assert result.structured_content["phase"] == "7-controlled-terminal-boundary"
    assert result.structured_content["write_enabled"] is True
    assert result.structured_content["terminal_enabled"] is False
    assert result.structured_content["git_enabled"] is True
    assert result.structured_content["git_write_enabled"] is True
    assert result.structured_content["orchestration_enabled"] is False
    assert result.structured_content["orchestration"] == {
        "task_read": False,
        "agent_read": False,
        "workflow_execute": False,
        "workflow_cancel": False,
        "execution_observability": False,
    }
