import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.server import create_server


@pytest.mark.anyio
async def test_server_lists_phase_0_2_tools(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}

    assert names == {"bridge_health", "workspace_validate_path"}


@pytest.mark.anyio
async def test_health_is_read_only_and_reports_write_disabled(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("bridge_health", {})

    assert result.is_error is False
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["write_enabled"] is False


@pytest.mark.anyio
async def test_path_tool_does_not_expose_absolute_workspace_path(tmp_path):
    source = tmp_path / "runtime"
    source.mkdir()
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "workspace_validate_path",
            {"path": "runtime", "expected_kind": "directory"},
        )

    assert result.structured_content["authorized"] is True
    assert result.structured_content["path"] == "runtime"
    assert str(tmp_path.resolve()) not in str(result.structured_content)
