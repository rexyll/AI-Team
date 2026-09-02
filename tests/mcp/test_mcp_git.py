import subprocess

import pytest

pytest.importorskip("mcp")

from mcp import Client

from mcp_bridge.config import MCPBridgeConfig
from mcp_bridge.git import MCPGitCapabilityBoundary
from mcp_bridge.server import create_server


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "MCP Test")
    (tmp_path / "example.txt").write_text("hello\n", encoding="utf-8")
    _git(tmp_path, "add", "example.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_boundary_allowlists_git_operations(tmp_path):
    boundary = MCPGitCapabilityBoundary(_repo(tmp_path))
    assert boundary.status()["operation"] == "status"
    assert boundary.branch()["operation"] == "branch"
    with pytest.raises(PermissionError, match="not allowed"):
        boundary.execute("push")


def test_boundary_bounds_git_output(tmp_path):
    repo = _repo(tmp_path)
    boundary = MCPGitCapabilityBoundary(repo, max_output_chars=20)
    result = boundary.log(max_count=20)
    assert result["truncated"] is True
    assert len(result["output"]) == 20


def test_boundary_rejects_workspace_outside_git_repository(tmp_path):
    repo = _repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    boundary = MCPGitCapabilityBoundary(repo)
    with pytest.raises(PermissionError):
        boundary.status(str(outside))


def test_boundary_rejects_direct_git_metadata_path(tmp_path):
    repo = _repo(tmp_path)
    boundary = MCPGitCapabilityBoundary(repo)
    with pytest.raises(PermissionError, match="Git metadata"):
        boundary.status(".git")


@pytest.mark.anyio
async def test_server_exposes_phase_5_git_tools(tmp_path):
    repo = _repo(tmp_path)
    server = create_server(MCPBridgeConfig(workspace_root=repo))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
    assert names == {
        "bridge_health", "bridge_readiness", "workspace_validate_path", "workspace_list_files",
        "workspace_read_file", "workspace_search_text", "workspace_write_file",
        "workspace_delete_file", "git_status", "git_diff", "git_log", "git_show",
        "git_branch", "git_rev_parse", "git_add", "git_commit",
    }


@pytest.mark.anyio
async def test_server_git_read_and_mutation_are_bounded(tmp_path):
    repo = _repo(tmp_path)
    (repo / "change.txt").write_text("change\n", encoding="utf-8")
    server = create_server(MCPBridgeConfig(workspace_root=repo))
    async with Client(server, raise_exceptions=True) as client:
        status = await client.call_tool("git_status", {})
        add = await client.call_tool("git_add", {"path": ".", "paths": ["change.txt"]})
        commit = await client.call_tool("git_commit", {"path": ".", "message": "add change"})
    assert status.is_error is False
    assert "change.txt" in status.structured_content["output"]
    assert add.is_error is False
    assert commit.is_error is False
    assert "add change" in commit.structured_content["output"].lower()


@pytest.mark.anyio
async def test_server_rejects_unsafe_git_revision(tmp_path):
    repo = _repo(tmp_path)
    server = create_server(MCPBridgeConfig(workspace_root=repo))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("git_show", {"revision": "--stat"})
    assert result.is_error is True


@pytest.mark.anyio
async def test_server_rejects_direct_git_metadata_path(tmp_path):
    repo = _repo(tmp_path)
    server = create_server(MCPBridgeConfig(workspace_root=repo))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("git_status", {"path": ".git"})
    assert result.is_error is True
