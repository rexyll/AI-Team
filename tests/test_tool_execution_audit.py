from __future__ import annotations

from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


def _record(
    execution_id: str,
    *,
    task_id: str = "TASK-001",
    role: str = "developer",
    tool: str = "read_file",
    status: str = "completed",
) -> ToolExecutionRecord:
    error = None if status == "completed" else {
        "message": f"tool execution {status}",
    }

    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id=task_id,
        agent_role=role,
        tool_name=tool,
        started_at="2026-08-21T00:00:00+00:00",
        completed_at="2026-08-21T00:01:00+00:00",
        status=status,
        arguments={"path": "src/app.py"},
        output={"execution": execution_id},
        error=error,
        metadata={},
    )


def _audit() -> ToolExecutionAudit:
    return ToolExecutionAudit(
        ToolExecutionHistory.from_dict(
            [
                _record("TOOL-001"),
                _record("TOOL-002", task_id="TASK-002", tool="write_file"),
                _record("TOOL-003", role="tester", status="failed"),
            ]
        )
    )


def test_audit_filters_by_all_supported_dimensions():
    audit = _audit()

    assert [r.execution_id for r in audit.records(task_id="TASK-002")] == ["TOOL-002"]
    assert [r.execution_id for r in audit.records(agent_role="tester")] == ["TOOL-003"]
    assert [r.execution_id for r in audit.records(tool_name="read_file")] == ["TOOL-001"]
    assert [r.execution_id for r in audit.records(status="failed")] == ["TOOL-003"]
    assert [r.execution_id for r in audit.records(task_id="TASK-002", tool_name="write_file")] == ["TOOL-002"]


def test_audit_count_uses_same_filter_contract():
    audit = _audit()
    assert audit.count() == 3
    assert audit.count(status="completed") == 2
    assert audit.count(agent_role="tester", status="failed") == 1


def test_audit_summary_is_deterministic():
    assert _audit().summary() == {
        "total": 3,
        "by_status": {"completed": 2, "failed": 1},
        "by_tool": {"read_file": 2, "write_file": 1},
        "by_agent_role": {"developer": 2, "tester": 1},
    }


def test_audit_is_read_only_and_rejects_invalid_history():
    audit = _audit()
    before = audit.history.to_dict()
    records = audit.records()
    records[0].arguments["path"] = "mutated-locally"
    assert audit.history.to_dict() == before

    try:
        ToolExecutionAudit(object())
    except TypeError:
        pass
    else:
        raise AssertionError("invalid history must be rejected")
