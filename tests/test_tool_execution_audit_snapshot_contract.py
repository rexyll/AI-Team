from __future__ import annotations

from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


def _record(execution_id: str, *, task_id: str = "TASK-001") -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id=task_id,
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-21T00:00:00+00:00",
        completed_at="2026-08-21T00:01:00+00:00",
        status="completed",
        arguments={"path": "src/app.py"},
        output={"execution": execution_id},
        error=None,
        metadata={},
    )


def test_audit_captures_an_immutable_history_snapshot():
    history = ToolExecutionHistory()
    history.append(_record("TOOL-001"))
    audit = ToolExecutionAudit(history)

    history.append(_record("TOOL-002"))

    assert [record.execution_id for record in audit.records()] == ["TOOL-001"]


def test_audit_history_property_is_detached_from_audit_state():
    history = ToolExecutionHistory()
    history.append(_record("TOOL-001"))
    audit = ToolExecutionAudit(history)

    exposed = audit.history
    exposed.append(_record("TOOL-002"))

    assert [record.execution_id for record in audit.records()] == ["TOOL-001"]
    assert [payload["execution_id"] for payload in history.to_dict()] == ["TOOL-001"]


def test_audit_returns_detached_records():
    history = ToolExecutionHistory()
    history.append(_record("TOOL-001"))
    audit = ToolExecutionAudit(history)

    record = audit.records()[0]
    record.arguments["path"] = "mutated"

    assert audit.records()[0].arguments["path"] == "src/app.py"


def test_audit_count_and_records_share_the_same_snapshot():
    history = ToolExecutionHistory()
    history.append(_record("TOOL-001"))
    audit = ToolExecutionAudit(history)
    history.append(_record("TOOL-002"))

    assert audit.count() == len(audit.records()) == 1
