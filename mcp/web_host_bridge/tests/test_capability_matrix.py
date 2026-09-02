from __future__ import annotations

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from web_host_bridge.config import MCPBridgeConfig
from web_host_bridge.server import create_server


READ_TOOLS = {
    "bridge_health",
    "bridge_readiness",
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

WORKSPACE_WRITE_TOOLS = {"workspace_write_file", "workspace_delete_file"}
GIT_WRITE_TOOLS = {"git_add", "git_commit"}
TERMINAL_TOOLS = {
    "terminal_execute",
    "terminal_execution_status",
    "terminal_execution_history",
}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("profile", "terminal_requested", "expected_mutations", "expected_terminal"),
    [
        ("developer", True, WORKSPACE_WRITE_TOOLS | GIT_WRITE_TOOLS, TERMINAL_TOOLS),
        ("readonly", True, set(), set()),
        ("production", True, set(), set()),
    ],
)
async def test_capability_matrix_matches_registered_tools(
    tmp_path,
    profile: str,
    terminal_requested: bool,
    expected_mutations: set[str],
    expected_terminal: set[str],
) -> None:
    config = MCPBridgeConfig(workspace_root=tmp_path, policy_profile=profile)
    server = create_server(config, terminal=terminal_requested)

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
        health = await client.call_tool("bridge_health", {})

    assert names == READ_TOOLS | expected_mutations | expected_terminal
    assert health.is_error is False
    payload = health.structured_content
    assert payload["policy_profile"] == profile
    assert payload["transport"] == "stdio"
    assert payload["write_enabled"] is (profile == "developer")
    assert payload["git_write_enabled"] is (profile == "developer")
    assert payload["terminal_enabled"] is (profile == "developer")


@pytest.mark.anyio
async def test_capability_matrix_read_tools_are_registered_for_every_profile(tmp_path) -> None:
    for profile in ("developer", "readonly", "production"):
        config = MCPBridgeConfig(workspace_root=tmp_path, policy_profile=profile)
        server = create_server(config)

        async with Client(server, raise_exceptions=True) as client:
            result = await client.list_tools()
            names = {tool.name for tool in result.tools}

        assert READ_TOOLS <= names
