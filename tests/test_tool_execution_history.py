from __future__ import annotations

import pytest

from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_persistence import ToolExecutionPersistenceAdapter
from runtime.tool_execution_record import ToolExecutionRecord


def _record(**overrides) -> ToolExecutionRecord:
    values = {
        "execution_id": "TOOL-001",
        "task_id": "TASK-001",
        "agent_role": "developer",
        "tool_name": "read_file",
        "started_at": "2026-08-21T00:00:00+00:00",
        "completed_at": "2026-08-21T00:00:01+00:00",
        "status": "completed",
        "arguments": {"path": "src/app.py"},
        "output": {"bytes": 42},
        "error": None,
        "metadata": {"iteration": 1},
    }
    values.update(overrides)
    return ToolExecutionRecord(**values)


def test_tool_execution_record_round_trip_and_detachment():
    record = _record(arguments={"options": {"paths": ["src/app.py"]}})
    payload = record.to_dict()
    payload["arguments"]["options"]["paths"].append("src/test.py")

    restored = ToolExecutionRecord.from_dict(record.to_dict())

    assert restored == record
    assert restored.arguments == {"options": {"paths": ["src/app.py"]}}


def test_tool_execution_record_rejects_invalid_status():
    with pytest.raises(ValueError, match="invalid tool execution status"):
        _record(status="running")


def test_tool_execution_record_requires_error_for_non_completed_status():
    with pytest.raises(ValueError, match="must contain an error"):
        _record(status="failed", error=None)


def test_tool_execution_history_indexes_records():
    history = ToolExecutionHistory()
    history.append(_record())
    history.append(
        _record(
            execution_id="TOOL-002",
            tool_name="run_command",
            started_at="2026-08-21T00:00:02+00:00",
            completed_at="2026-08-21T00:00:03+00:00",
            arguments={"command": "pytest -q"},
            output="1 passed",
        )
    )

    assert len(history) == 2
    assert history.list_for_task("TASK-001")[0].execution_id == "TOOL-001"
    assert history.list_for_tool("run_command")[0].execution_id == "TOOL-002"


def test_tool_execution_history_rejects_duplicate_ids():
    history = ToolExecutionHistory()
    history.append(_record())

    with pytest.raises(ValueError, match="execution_id already exists"):
        history.append(_record())


def test_tool_execution_history_round_trip():
    history = ToolExecutionHistory()
    history.append(_record())

    restored = ToolExecutionHistory.from_dict(history.to_dict())

    assert restored.get("TOOL-001") == history.get("TOOL-001")


def test_tool_execution_persistence_round_trip_and_identity(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    record = _record()

    adapter.save(record)

    assert adapter.list_ids() == ["TOOL-001"]
    assert adapter.load("TOOL-001") == record

    with pytest.raises(FileExistsError):
        adapter.save(record)


def test_tool_execution_persistence_rejects_corrupt_payload(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    (tmp_path / "TOOL-001.json").write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid tool execution record"):
        adapter.load("TOOL-001")


def test_tool_execution_history_can_save_to_persistence(tmp_path):
    history = ToolExecutionHistory()
    history.append(_record())
    adapter = ToolExecutionPersistenceAdapter(tmp_path)

    history.save(adapter)

    assert adapter.load("TOOL-001") == history.get("TOOL-001")
