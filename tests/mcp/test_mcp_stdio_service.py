from __future__ import annotations

import sys
from pathlib import Path

import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters


@pytest.mark.anyio
async def test_standalone_mcp_service_connects_over_stdio(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_bridge"],
        cwd=str(repo_root),
        env={"AI_TEAM_WORKSPACE": str(tmp_path)},
    )

    async with Client(server_params) as client:
        tools = await client.list_tools()
        health = await client.call_tool("bridge_health", {})

    names = {tool.name for tool in tools.tools}
    assert "bridge_health" in names
    assert "workspace_read_file" in names
    assert "workspace_write_file" not in names
    assert "git_commit" not in names
    assert "terminal_execute" not in names
    assert health.is_error is False
    assert health.structured_content["transport"] == "stdio"
    assert health.structured_content["policy_profile"] == "readonly"
    assert health.structured_content["write_enabled"] is False
    assert health.structured_content["terminal_enabled"] is False
    assert health.structured_content["git_write_enabled"] is False
