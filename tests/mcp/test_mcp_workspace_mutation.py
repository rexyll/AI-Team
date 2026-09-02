import pytest

mcp_sdk = pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.server import create_server
from mcp_bridge.workspace_mutation import MCPWorkspaceMutationBoundary, WorkspaceMutationEvent


@pytest.mark.anyio
async def test_server_lists_phase_4_mutation_tools(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}

    assert names == {
        "bridge_health",
        "workspace_validate_path",
        "workspace_list_files",
        "workspace_read_file",
        "workspace_search_text",
        "workspace_write_file",
        "workspace_delete_file",
    }


@pytest.mark.anyio
async def test_health_reports_secure_mutation_phase(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("bridge_health", {})

    assert result.structured_content["phase"] == "4-secure-workspace-mutation"
    assert result.structured_content["write_enabled"] is True
    assert result.structured_content["terminal_enabled"] is False
    assert result.structured_content["git_write_enabled"] is False


@pytest.mark.anyio
async def test_write_requires_explicit_overwrite_for_existing_file(tmp_path):
    source = tmp_path / "example.txt"
    source.write_text("old", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        rejected = await client.call_tool(
            "workspace_write_file",
            {"path": "example.txt", "content": "new"},
        )
        updated = await client.call_tool(
            "workspace_write_file",
            {"path": "example.txt", "content": "new", "overwrite": True},
        )

    assert rejected.is_error is True
    assert updated.structured_content == {
        "result": {"path": "example.txt", "operation": "update", "bytes_written": 3}
    }
    assert source.read_text(encoding="utf-8") == "new"


@pytest.mark.anyio
async def test_write_creates_nested_file_and_returns_relative_path(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "workspace_write_file",
            {"path": "generated/example.txt", "content": "hello"},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "result": {"path": "generated/example.txt", "operation": "create", "bytes_written": 5}
    }
    assert (tmp_path / "generated/example.txt").read_text(encoding="utf-8") == "hello"
    assert str(tmp_path.resolve()) not in str(result.structured_content)


@pytest.mark.anyio
async def test_delete_file_is_bounded_and_returns_relative_path(tmp_path):
    source = tmp_path / "delete-me.txt"
    source.write_text("bye", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("workspace_delete_file", {"path": "delete-me.txt"})

    assert result.structured_content == {
        "result": {"path": "delete-me.txt", "operation": "delete"}
    }
    assert not source.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("path", [".git/config", ".venv/x.txt", "__pycache__/x.pyc"])
async def test_mutations_reject_ignored_directories(tmp_path, path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "workspace_write_file",
            {"path": path, "content": "blocked"},
        )

    assert result.is_error is True
    assert not (tmp_path / path).exists()


@pytest.mark.anyio
async def test_mutation_rejects_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "workspace_write_file",
            {"path": "../outside.txt", "content": "blocked"},
        )

    assert result.is_error is True
    assert not outside.exists()


@pytest.mark.anyio
async def test_write_enforces_byte_limit(tmp_path):
    server = create_server(MCPBridgeConfig(workspace_root=tmp_path))

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "workspace_write_file",
            {"path": "large.txt", "content": "x" * 32, "max_bytes": 16},
        )

    assert result.is_error is True
    assert not (tmp_path / "large.txt").exists()


def test_mutation_boundary_emits_audit_event_only_after_success(tmp_path):
    events: list[WorkspaceMutationEvent] = []
    boundary = MCPWorkspaceMutationBoundary(tmp_path, audit_sink=events.append)

    boundary.write_file("created.txt", "hello")
    boundary.write_file("created.txt", "updated", overwrite=True)
    boundary.delete_file("created.txt")

    assert events == [
        WorkspaceMutationEvent("create", "created.txt", 5),
        WorkspaceMutationEvent("update", "created.txt", 7),
        WorkspaceMutationEvent("delete", "created.txt", 0),
    ]
