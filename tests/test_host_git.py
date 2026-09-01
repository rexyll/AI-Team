from pathlib import Path

import pytest

from runtime.host_git import GitOperationRequest, HostGitOperationService
from security.runtime_capability import HOST_ONLY_TOOLS, RuntimeCapabilityPolicy
from security.tool_permission import ToolPermissionError
from security.workspace import WorkspaceSandbox
from tools.registry import TOOL_REGISTRY


OPERATIONS = {
    "status", "diff", "log", "show", "branch", "rev-parse", "add", "commit"
}


def _service(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    calls = []

    def fake_git(command: str, cwd: str) -> str:
        calls.append((command, cwd))
        if command == "rev-parse --show-toplevel":
            return f"exit_code=0\n{workspace}\n"
        return "exit_code=0\nok\n"

    monkeypatch.setattr("runtime.host_git.git_tool.git_command", fake_git)
    return HostGitOperationService(WorkspaceSandbox(tmp_path)), workspace, calls


def test_host_service_exposes_only_semantic_git_operations():
    assert "command" not in GitOperationRequest.__dataclass_fields__
    assert OPERATIONS == {
        value for value in GitOperationRequest.__dataclass_fields__["operation"].type.__args__
    }


def test_agent_registry_does_not_expose_raw_git_command():
    assert "git_command" not in TOOL_REGISTRY.list()


def test_raw_git_is_host_only_for_every_agent_role():
    policy = RuntimeCapabilityPolicy()
    assert HOST_ONLY_TOOLS == {"git_command"}
    for role in ("architect", "developer", "tester", "reviewer", "planner"):
        assert not policy.allows(role, "git_command")
        with pytest.raises(ToolPermissionError, match="host-only"):
            policy.require(role, "git_command")
        assert "git_command" not in policy.filter_tool_names(role, ["git_command"])


def test_status_is_host_owned_and_validates_repository(tmp_path, monkeypatch):
    service, workspace, calls = _service(tmp_path, monkeypatch)
    assert service.status(str(workspace)) == "exit_code=0\nok\n"
    assert calls == [
        ("rev-parse --show-toplevel", str(workspace)),
        ("status --short", str(workspace)),
    ]


def test_add_anchors_relative_paths_to_repository_workspace(tmp_path, monkeypatch):
    service, workspace, calls = _service(tmp_path, monkeypatch)
    target = workspace / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("pass", encoding="utf-8")

    service.add(str(workspace), ["src/app.py"])

    expected = str(Path("src") / "app.py")
    assert calls[-1] == (f'add "{expected}"', str(workspace))


def test_add_rejects_workspace_escape(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        service.add(str(workspace), ["../outside.txt"])


def test_commit_rejects_empty_and_multiline_messages(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="non-empty"):
        service.commit(str(workspace), "   ")
    with pytest.raises(ValueError, match="single-line"):
        service.commit(str(workspace), "first\nsecond")


def test_revision_rejects_option_injection(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="must not start"):
        service.show(str(workspace), revision="--output=/tmp/x")
