from __future__ import annotations

import json

import pytest

from runtime.execution_record import AgentExecutionRecord
from runtime.execution_record_persistence import ExecutionRecordPersistenceAdapter


def _record(execution_id: str = "EXEC-001") -> AgentExecutionRecord:
    return AgentExecutionRecord(
        execution_id=execution_id,
        project_id="PROJECT-001",
        task_id="TASK-001",
        agent_role="developer",
        stage="developer",
        attempt=1,
        started_at="2026-08-21T10:00:00+00:00",
        completed_at="2026-08-21T10:00:02+00:00",
        status="completed",
        outcome="success",
        result={"message": "ok"},
        error=None,
        metadata={"model": "test"},
    )


def test_execution_record_round_trip(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    record = _record()
    adapter.save(record)
    assert adapter.load("EXEC-001") == record


def test_execution_record_persistence_is_json_serializable(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    adapter.save(_record())
    payload = json.loads((tmp_path / "EXEC-001.json").read_text(encoding="utf-8"))
    json.dumps(payload)
    assert payload["execution_id"] == "EXEC-001"


def test_duplicate_execution_id_is_rejected(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    adapter.save(_record())
    with pytest.raises(FileExistsError):
        adapter.save(_record())


def test_missing_execution_record_is_explicit(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    with pytest.raises(KeyError):
        adapter.load("MISSING")
    with pytest.raises(KeyError):
        adapter.delete("MISSING")


def test_list_ids_is_sorted_and_ignores_unrelated_files(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    adapter.save(_record("EXEC-002"))
    adapter.save(_record("EXEC-001"))
    (tmp_path / "README.txt").write_text("ignore", encoding="utf-8")
    assert adapter.list_ids() == ["EXEC-001", "EXEC-002"]


def test_delete_removes_only_requested_record(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    adapter.save(_record("EXEC-001"))
    adapter.save(_record("EXEC-002"))
    adapter.delete("EXEC-001")
    assert adapter.list_ids() == ["EXEC-002"]


def test_corrupt_json_is_rejected(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    (tmp_path / "EXEC-001.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        adapter.load("EXEC-001")


def test_identity_mismatch_is_rejected(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    payload = _record("OTHER").to_dict()
    (tmp_path / "EXEC-001.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        adapter.load("EXEC-001")


def test_runtime_objects_are_not_persisted(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    record = _record()
    adapter.save(record)
    raw = (tmp_path / "EXEC-001.json").read_text(encoding="utf-8")
    assert "TaskManager" not in raw
    assert "Agent" not in raw
    assert "Workflow" not in raw
