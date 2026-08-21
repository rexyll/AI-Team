import pytest

from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_persistence import ToolExecutionPersistenceAdapter
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


def test_save_if_absent_many_deduplicates_and_returns_new_count(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    first = record("TOOL-001")
    second = record("TOOL-002")
    adapter.save(first)

    assert adapter.save_if_absent_many([first, second, second]) == 1
    assert adapter.list_ids() == ["TOOL-001", "TOOL-002"]
    assert adapter.load("TOOL-002") == second


def test_save_if_absent_many_rejects_conflicts_before_writing(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    adapter.save(record("TOOL-001"))

    with pytest.raises(FileExistsError):
        adapter.save_if_absent_many(
            [
                record("TOOL-002"),
                record("TOOL-001", message="changed"),
            ]
        )

    assert adapter.list_ids() == ["TOOL-001"]
    with pytest.raises(KeyError):
        adapter.load("TOOL-002")


def test_history_save_if_absent_uses_batch_semantics(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    history = ToolExecutionHistory()
    history.append(record("TOOL-001"))
    history.append(record("TOOL-002"))

    assert history.save_if_absent(adapter) == 2
    assert history.save_if_absent(adapter) == 0
    assert adapter.list_ids() == ["TOOL-001", "TOOL-002"]
