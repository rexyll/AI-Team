import pytest

from mcp_bridge.terminal import MCPTerminalCapabilityBoundary


@pytest.fixture
def boundary(tmp_path):
    return MCPTerminalCapabilityBoundary(str(tmp_path))


def test_execute_returns_bounded_relative_result(boundary, monkeypatch):
    monkeypatch.setattr("mcp_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=0\nhello")
    result = boundary.execute("python --version")
    assert result == {
        "command": "python --version",
        "cwd": ".",
        "output": "hello",
        "exit_code": 0,
        "timed_out": False,
        "truncated": False,
    }


def test_execute_truncates_output(boundary, monkeypatch):
    monkeypatch.setattr("mcp_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=0\n" + "x" * 20)
    result = boundary.execute("python --version", max_output_chars=8)
    assert result["truncated"] is True
    assert result["output"] == "xxxxxxxx\n[output truncated by MCP terminal boundary]"


def test_execute_rejects_disallowed_executable(boundary):
    with pytest.raises(PermissionError, match="Executable is not allowed"):
        boundary.execute("powershell.exe Get-ChildItem")


def test_execute_rejects_shell_chaining(boundary):
    with pytest.raises(PermissionError, match="Shell chaining"):
        boundary.execute("python --version && whoami")


def test_execute_rejects_multiline_command(boundary):
    with pytest.raises(PermissionError, match="Multi-line"):
        boundary.execute("python --version\nwhoami")


def test_execute_rejects_blocked_code_argument(boundary):
    with pytest.raises(PermissionError, match="Code-evaluation"):
        boundary.execute("python -c print(1)")


def test_execute_rejects_workspace_escape(boundary):
    with pytest.raises(PermissionError):
        boundary.execute("python --version", "../outside")


def test_execute_rejects_invalid_limits(boundary):
    with pytest.raises(ValueError, match="timeout"):
        boundary.execute("python --version", timeout=121)
    with pytest.raises(ValueError, match="max_output_chars"):
        boundary.execute("python --version", max_output_chars=0)


def test_execute_requires_directory_cwd(boundary, tmp_path, monkeypatch):
    source = tmp_path / "file.txt"
    source.write_text("x", encoding="utf-8")
    monkeypatch.setattr("mcp_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=0\nok")
    with pytest.raises(NotADirectoryError, match="Terminal cwd must be a directory"):
        boundary.execute("python --version", "file.txt")


def test_execute_audits_successful_result(tmp_path, monkeypatch):
    events = []
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path), audit_sink=events.append)
    monkeypatch.setattr("mcp_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=1\nfailed")
    result = boundary.execute("python --version")
    assert result["exit_code"] == 1
    assert len(events) == 1
    assert events[0].exit_code == 1
    assert events[0].cwd == "."


def test_execute_propagates_timeout_and_does_not_forge_success(monkeypatch, tmp_path):
    events = []
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path), audit_sink=events.append)

    def timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("mcp_bridge.terminal.run_command", timeout)
    with pytest.raises(TimeoutError, match="timed out"):
        boundary.execute("python --version", timeout=1)
    assert events == []
