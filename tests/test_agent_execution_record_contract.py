from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from runtime.execution_record import AgentExecutionRecord


def _record(**overrides):
    payload = {
        "execution_id": "EXEC-001",
        "project_id": "PROJECT-001",
        "task_id": "TASK-001",
        "agent_role": "developer",
        "stage": "developer",
        "attempt": 1,
        "started_at": "2026-08-21T10:00:00+00:00",
        "completed_at": "2026-08-21T10:00:02+00:00",
        "status": "completed",
        "outcome": "success",
        "result": {"message": "implemented"},
        "error": None,
        "metadata": {"model": "test-model"},
    }
    payload.update(overrides)
    return AgentExecutionRecord(**payload)


def test_execution_record_is_json_serializable():
    record = _record()
    payload = record.to_dict()
    json.dumps(payload)
    assert payload["execution_id"] == "EXEC-001"


def test_execution_record_round_trip_preserves_state():
    record = _record()
    restored = AgentExecutionRecord.from_dict(record.to_dict())
    assert restored == record


def test_execution_record_is_immutable():
    record = _record()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        record.status = "failed"  # type: ignore[misc]


def test_execution_record_rejects_invalid_identity():
    with pytest.raises(ValueError):
        _record(execution_id="")
    with pytest.raises(ValueError):
        _record(project_id="")
    with pytest.raises(ValueError):
        _record(task_id="")


def test_execution_record_rejects_invalid_attempt():
    with pytest.raises(ValueError):
        _record(attempt=0)
    with pytest.raises(TypeError):
        _record(attempt="1")  # type: ignore[arg-type]


def test_execution_record_rejects_invalid_status_and_outcome():
    with pytest.raises(ValueError):
        _record(status="unknown")
    with pytest.raises(ValueError):
        _record(outcome="unknown")


def test_execution_record_rejects_runtime_objects():
    class RuntimeObject:
        pass

    with pytest.raises(TypeError):
        _record(result=RuntimeObject())
    with pytest.raises(TypeError):
        _record(metadata={"runtime": RuntimeObject()})


def test_execution_record_keeps_error_serializable():
    record = _record(status="failed", outcome="failure", error={"type": "ValueError", "message": "boom"})
    restored = AgentExecutionRecord.from_dict(record.to_dict())
    assert restored.error == record.error


def test_execution_record_is_separate_from_task_lifecycle_history():
    record = _record()
    assert "status_history" not in record.to_dict()
    assert "task" not in record.to_dict()
    assert "agent" not in record.to_dict()
