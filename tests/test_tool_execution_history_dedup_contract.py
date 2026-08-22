from __future__ import annotations

import json

import pytest

from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.tool_execution_history import ToolExecutionConflictError, ToolExecutionHistory
from runtime.tool_execution_persistence import ToolExecutionPersistenceAdapter
from runtime.tool_execution_record import ToolExecutionRecord


def _record(**overrides) -> ToolExecutionRecord:
    values = {
        "execution_id": "TOOL-001",
        "task_id": "TASK-001",
        "agent_role": "developer",
        "tool_name": "read_file",
        "started_at": "2026-08-22T00:00:00+00:00",
        "completed_at": "2026-08-22T00:00:01+00:00",
        "status": "completed",
        "arguments": {"path": "src/app.py"},
        "output": {"bytes": 42},
        "error": None,
        "metadata": {"iteration": 1},
    }
    values.update(overrides)
    return ToolExecutionRecord(**values)


def test_history_from_dict_deduplicates_identical_execution_records():
    record = _record()

    history = ToolExecutionHistory.from_dict([record.to_dict(), record.to_dict()])

    assert len(history) == 1
    assert history.get(record.execution_id) == record


def test_history_from_dict_rejects_conflicting_execution_records_atomically():
    first = _record()
    conflicting = _record(output={"bytes": 99})

    with pytest.raises(ToolExecutionConflictError, match="TOOL-001"):
        ToolExecutionHistory.from_dict([first.to_dict(), conflicting.to_dict()])


def test_history_merge_rejects_conflict_without_mutating_existing_history():
    history = ToolExecutionHistory()
    existing = _record()
    history.append(existing)

    with pytest.raises(ToolExecutionConflictError):
        history.merge(
            [
                _record(execution_id="TOOL-002"),
                _record(output={"bytes": 99}),
            ]
        )

    assert history.to_dict() == [existing.to_dict()]


def test_history_append_if_absent_uses_same_conflict_type_as_merge():
    history = ToolExecutionHistory()
    history.append(_record())

    with pytest.raises(ToolExecutionConflictError):
        history.append_if_absent(_record(tool_name="run_command"))


def test_persistence_save_if_absent_uses_same_conflict_type_as_history(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    record = _record()
    adapter.save(record)

    with pytest.raises(ToolExecutionConflictError):
        adapter.save_if_absent(_record(tool_name="run_command"))


def test_persistence_batch_deduplicates_identical_input_records(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    record = _record()

    assert adapter.save_if_absent_many([record, record]) == 1
    assert adapter.list_ids() == ["TOOL-001"]


def test_persistence_batch_rejects_conflicting_input_before_writes(tmp_path):
    adapter = ToolExecutionPersistenceAdapter(tmp_path)
    first = _record()
    conflicting = _record(output={"bytes": 99})

    with pytest.raises(ToolExecutionConflictError):
        adapter.save_if_absent_many([first, conflicting])

    assert adapter.list_ids() == []


def test_project_recovery_deduplicates_identical_task_context_records(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    record = _record()
    payload = {
        "project_id": "PROJECT-001",
        "plan": {"project": "dedup", "tasks": []},
        "tasks": [
            {
                "id": "TASK-001",
                "title": "tool task",
                "description": "dedup",
                "role": "developer",
                "dependencies": [],
                "status": "ready",
                "result": None,
                "context": {"tool_execution_history": [record.to_dict(), record.to_dict()]},
            }
        ],
        "result": None,
        "tool_execution_history": None,
    }
    (tmp_path / "PROJECT-001.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    snapshot = adapter.load("PROJECT-001")

    assert snapshot.tool_execution_history is not None
    assert len(snapshot.tool_execution_history) == 1


def test_project_recovery_rejects_conflicting_task_context_records(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    first = _record()
    conflicting = _record(output={"bytes": 99})
    payload = {
        "project_id": "PROJECT-002",
        "plan": {"project": "conflict", "tasks": []},
        "tasks": [
            {
                "id": "TASK-001",
                "title": "tool task",
                "description": "conflict",
                "role": "developer",
                "dependencies": [],
                "status": "ready",
                "result": None,
                "context": {"tool_execution_history": [first.to_dict(), conflicting.to_dict()]},
            }
        ],
        "result": None,
        "tool_execution_history": None,
    }
    (tmp_path / "PROJECT-002.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="invalid tool execution history"):
        adapter.load("PROJECT-002")
