import pytest

from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord


def record(execution_id: str, *, message: str = "ok") -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        task_id="TASK-001",
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-21T10:00:00Z",
        completed_at="2026-08-21T10:00:01Z",
        status="completed",
        arguments={"path": "README.md"},
        output={"message": message},
        error=None,
        metadata={},
    )


def test_append_if_absent_ignores_identical_record():
    history = ToolExecutionHistory()
    first = record("TOOL-001")

    assert history.append_if_absent(first) is True
    assert history.append_if_absent(record("TOOL-001")) is False
    assert len(history) == 1
    assert history.get("TOOL-001") == first


def test_append_if_absent_rejects_conflicting_record():
    history = ToolExecutionHistory()
    history.append(record("TOOL-001"))

    with pytest.raises(ValueError, match="conflicting tool execution record"):
        history.append_if_absent(record("TOOL-001", message="changed"))

    assert len(history) == 1
    assert history.get("TOOL-001").output == {"message": "ok"}


def test_merge_deduplicates_identical_records_and_returns_new_count():
    history = ToolExecutionHistory()
    history.append(record("TOOL-001"))

    added = history.merge(
        [
            record("TOOL-001"),
            record("TOOL-002"),
            record("TOOL-002"),
        ]
    )

    assert added == 1
    assert len(history) == 2
    assert [item.execution_id for item in history.list_for_task("TASK-001")] == [
        "TOOL-001",
        "TOOL-002",
    ]


def test_merge_is_atomic_when_a_conflict_is_found():
    history = ToolExecutionHistory()
    history.append(record("TOOL-001"))

    with pytest.raises(ValueError, match="conflicting tool execution record"):
        history.merge(
            [
                record("TOOL-002"),
                record("TOOL-001", message="changed"),
                record("TOOL-003"),
            ]
        )

    assert len(history) == 1
    assert history.get("TOOL-001").output == {"message": "ok"}
    with pytest.raises(KeyError):
        history.get("TOOL-002")
