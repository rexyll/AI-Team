from __future__ import annotations

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.server import create_server


@pytest.mark.anyio
async def test_production_profile_exposes_only_read_capabilities(tmp_path):
    config = MCPBridgeConfig(workspace_root=tmp_path, policy_profile="production")
    server = create_server(config, terminal=True)

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
        health = await client.call_tool("bridge_health", {})

    assert names == {
        "bridge_health",
        "workspace_validate_path",
        "workspace_list_files",
        "workspace_read_file",
        "workspace_search_text",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch",
        "git_rev_parse",
    }
    assert health.is_error is False
    assert health.structured_content["policy_profile"] == "production"
    assert health.structured_content["write_enabled"] is False
    assert health.structured_content["git_write_enabled"] is False
    assert health.structured_content["terminal_enabled"] is False
