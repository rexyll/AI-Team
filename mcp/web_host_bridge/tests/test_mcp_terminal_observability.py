import pytest

from web_host_bridge.terminal import MCPTerminalCapabilityBoundary
from runtime.workflow_event_log import WorkflowEventLog


def test_terminal_execution_is_recorded_in_canonical_workflow_event_log(tmp_path, monkeypatch):
    event_log = WorkflowEventLog()
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path), workflow_event_log=event_log, project_id="PROJECT-001")
    monkeypatch.setattr("web_host_bridge.terminal.run_command", lambda *args, **kwargs: "exit_code=0\nhello")
    result = boundary.execute("python --version")
    assert result["output"] == "hello"
    events = event_log.list_for_project("PROJECT-001")
    assert [event.event_type for event in events] == ["mcp_terminal_execution_requested", "mcp_terminal_execution_completed"]
    assert all(event.payload["source"] == "mcp" for event in events)
    assert events[0].payload["execution_id"] == events[1].payload["execution_id"]
    assert events[1].payload["exit_code"] == 0
    assert events[1].payload["status"] == "completed"
    assert events[1].payload["cwd"] == "."


def test_terminal_failure_is_recorded_without_forging_success(tmp_path, monkeypatch):
    event_log = WorkflowEventLog()
    boundary = MCPTerminalCapabilityBoundary(str(tmp_path), workflow_event_log=event_log, project_id="PROJECT-001")
    def fail(*args, **kwargs):
        raise TimeoutError("timed out")
    monkeypatch.setattr("web_host_bridge.terminal.run_command", fail)
    with pytest.raises(TimeoutError, match="timed out"):
        boundary.execute("python --version", timeout=1)
    events = event_log.list_for_project("PROJECT-001")
    assert [event.event_type for event in events] == ["mcp_terminal_execution_requested", "mcp_terminal_execution_failed"]
    assert events[1].payload["error_type"] == "TimeoutError"


def test_terminal_observability_requires_project_id_with_event_log(tmp_path):
    with pytest.raises(ValueError, match="project_id"):
        MCPTerminalCapabilityBoundary(str(tmp_path), workflow_event_log=WorkflowEventLog())


def test_terminal_observability_requires_event_log_with_project_id(tmp_path):
    with pytest.raises(ValueError, match="workflow_event_log"):
        MCPTerminalCapabilityBoundary(str(tmp_path), project_id="PROJECT-001")
