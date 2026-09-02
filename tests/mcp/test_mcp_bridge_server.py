import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.server import create_server


@pytest.mark.anyio
async def test_server_lists_phase_7_tools_when_terminal_enabled(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), terminal=True)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
    assert names == {"bridge_health", "workspace_validate_path", "workspace_list_files", "workspace_read_file", "workspace_search_text", "workspace_write_file", "workspace_delete_file", "git_status", "git_diff", "git_log", "git_show", "git_branch", "git_rev_parse", "git_add", "git_commit", "terminal_execute"}


@pytest.mark.anyio
async def test_standalone_server_keeps_terminal_disabled_by_default(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
    assert "terminal_execute" not in names


@pytest.mark.anyio
async def test_health_reports_phase_7_capability_phase(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path), terminal=True)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("bridge_health", {})
    assert result.is_error is False
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["phase"] == "7-controlled-terminal-boundary"
    assert result.structured_content["read_enabled"] is True
    assert result.structured_content["write_enabled"] is True
    assert result.structured_content["terminal_enabled"] is True
    assert result.structured_content["git_enabled"] is True
    assert result.structured_content["git_write_enabled"] is True
    assert result.structured_content["orchestration_enabled"] is False
    assert result.structured_content["orchestration"] == {"task_read": False, "agent_read": False, "workflow_execute": False, "workflow_cancel": False, "execution_observability": False, "execution_status": False, "execution_idempotency": False}


@pytest.mark.anyio
async def test_read_file_and_list_files_use_relative_paths(tmp_path):
    source = tmp_path / "runtime"
    source.mkdir()
    (source / "example.py").write_text("VALUE = 42\n", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.call_tool("workspace_list_files", {"path": "runtime"})
        content = await client.call_tool("workspace_read_file", {"path": "runtime/example.py"})
    assert listed.structured_content == {"result": ["runtime/example.py"]}
    assert content.structured_content == {"result": "VALUE = 42\n"}
    assert str(tmp_path.resolve()) not in str(listed.structured_content)
    assert str(tmp_path.resolve()) not in str(content.structured_content)


@pytest.mark.anyio
async def test_search_text_returns_bounded_relative_matches(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "example.py").write_text("first = 1\nTARGET = 42\nlast = 3\n", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("workspace_search_text", {"query": "target", "path": "src"})
    assert result.is_error is False
    assert result.structured_content == {"result": [{"path": "src/example.py", "line": 2, "text": "TARGET = 42"}]}


@pytest.mark.anyio
async def test_read_tools_reject_git_metadata(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("secret", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("workspace_read_file", {"path": ".git/config"})
    assert result.is_error is True
    assert str(result.content) == "[TextContent(type='text', text='Error executing tool workspace_read_file', annotations=None, meta=None)]"


@pytest.mark.anyio
async def test_read_file_enforces_size_limit(tmp_path):
    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * 32)
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("workspace_read_file", {"path": "large.txt", "max_bytes": 16})
    assert result.is_error is True
    assert str(result.content) == "[TextContent(type='text', text='Error executing tool workspace_read_file', annotations=None, meta=None)]"


@pytest.mark.anyio
async def test_read_tools_reject_paths_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("workspace_read_file", {"path": "../outside.txt"})
    assert result.is_error is True
    outside.unlink()
