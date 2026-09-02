import threading

import pytest

from mcp_bridge.terminal import MCPTerminalCapabilityBoundary


def test_terminal_execution_status_is_queryable_after_execution(tmp_path, monkeypatch):
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path))
    monkeypatch.setattr("mcp_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=0\nhello")

    boundary.execute("python --version")
    execution_id = boundary.execution_history(limit=1)[0]["execution_id"]
    status = boundary.execution_status(execution_id)

    assert status["execution_id"] == execution_id
    assert status["command"] == "python --version"
    assert status["cwd"] == "."
    assert status["status"] == "completed"
    assert status["started_at"]
    assert status["completed_at"]
    assert status["exit_code"] == 0
    assert status["timed_out"] is False
    assert status["truncated"] is False


def test_terminal_execution_failure_has_failed_control_state(tmp_path, monkeypatch):
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path))

    def fail(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("mcp_bridge.terminal.run_command", fail)
    with pytest.raises(TimeoutError):
        boundary.execute("python --version", timeout=1)

    history = boundary.execution_history()
    assert len(history) == 1
    execution_id = history[0]["execution_id"]
    status = boundary.execution_status(execution_id)
    assert status["status"] == "failed"
    assert status["error_type"] == "TimeoutError"
    assert "exit_code" not in status


def test_terminal_execution_history_is_bounded_and_newest_by_insertion_order(tmp_path, monkeypatch):
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path))
    monkeypatch.setattr("mcp_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=0\nok")

    first = boundary.execute("python --version")
    second = boundary.execute("python --version")

    history = boundary.execution_history(limit=1)
    assert len(history) == 1
    assert history[0]["execution_id"] != first.get("execution_id")
    assert history[0]["execution_id"] == boundary.execution_history(limit=2)[-1]["execution_id"]
    assert history[0]["execution_id"] != second.get("execution_id")


def test_terminal_execution_status_rejects_unknown_id(tmp_path):
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path))
    with pytest.raises(KeyError, match="Unknown terminal execution id"):
        boundary.execution_status("missing")


def test_terminal_execution_history_validates_limit(tmp_path):
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path))
    with pytest.raises(ValueError, match="limit"):
        boundary.execution_history(limit=0)
    with pytest.raises(ValueError, match="limit"):
        boundary.execution_history(limit=201)


def test_terminal_control_plane_isolated_for_concurrent_executions(tmp_path, monkeypatch):
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path))
    started = threading.Event()
    release = threading.Event()
    results = []

    def blocking(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return "exit_code=0\nok"

    monkeypatch.setattr("mcp_bridge.terminal.run_command", blocking)

    def worker():
        results.append(boundary.execute("python --version"))

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(2)
    active = boundary.execution_history()
    assert len(active) == 1
    assert active[0]["status"] == "active"
    execution_id = active[0]["execution_id"]
    assert boundary.execution_status(execution_id)["status"] == "active"
    release.set()
    thread.join(2)
    assert len(results) == 1
    assert boundary.execution_status(execution_id)["status"] == "completed"
