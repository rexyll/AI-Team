from __future__ import annotations

from agents.developer import DeveloperAgent
from runtime.llm.mock import MockLLM
from runtime.tool_execution_history import ToolExecutionHistory


def test_developer_agent_records_tool_execution_history():
    agent = DeveloperAgent(llm=MockLLM())
    agent.tool_execution_history = ToolExecutionHistory()

    agent._record_tool_execution(
        execution_id="call-001",
        task_id="TASK-001",
        tool_name="read_file",
        started_at="2026-08-21T00:00:00+00:00",
        status="completed",
        arguments={"path": "src/app.py"},
        output={"bytes": 10},
        error=None,
    )

    record = agent.tool_execution_history.get("call-001")
    assert record.task_id == "TASK-001"
    assert record.agent_role == "developer"
    assert record.tool_name == "read_file"
    assert record.status == "completed"
    assert record.arguments == {"path": "src/app.py"}
    assert record.output == {"bytes": 10}


def test_developer_agent_preserves_failed_tool_error_without_output():
    agent = DeveloperAgent(llm=MockLLM())
    agent.tool_execution_history = ToolExecutionHistory()

    agent._record_tool_execution(
        execution_id="call-002",
        task_id="TASK-002",
        tool_name="run_command",
        started_at="2026-08-21T00:00:00+00:00",
        status="failed",
        arguments={"command": "pytest -q"},
        output=None,
        error={"type": "RuntimeError", "message": "command failed"},
    )

    record = agent.tool_execution_history.get("call-002")
    assert record.status == "failed"
    assert record.output is None
    assert record.error == {
        "type": "RuntimeError",
        "message": "command failed",
    }
