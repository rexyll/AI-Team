from __future__ import annotations

import pytest

from runtime.execution_record import AgentExecutionRecord
from runtime.execution_history import ExecutionHistory


def _record(execution_id: str, task_id: str = "TASK-001", project_id: str = "PROJECT-001", attempt: int = 1) -> AgentExecutionRecord:
    return AgentExecutionRecord(
        execution_id=execution_id,
        project_id=project_id,
        task_id=task_id,
        agent_role="developer",
        stage="developer",
        attempt=attempt,
        started_at=f"2026-08-21T10:00:0{attempt}+00:00",
        completed_at=f"2026-08-21T10:00:1{attempt}+00:00",
        status="completed",
        outcome="success",
        result={"attempt": attempt},
        metadata={},
    )


def test_history_appends_and_returns_record():
    history = ExecutionHistory()
    record = _record("EXEC-001")
    history.append(record)
    assert history.get("EXEC-001") == record


def test_history_rejects_duplicate_execution_id():
    history = ExecutionHistory()
    history.append(_record("EXEC-001"))
    with pytest.raises(ValueError):
        history.append(_record("EXEC-001"))


def test_history_preserves_record_immutability():
    history = ExecutionHistory()
    record = _record("EXEC-001")
    history.append(record)
    assert history.get("EXEC-001") is record
    with pytest.raises((AttributeError, TypeError)):
        record.attempt = 2  # type: ignore[misc]


def test_history_lists_task_records_in_stable_order():
    history = ExecutionHistory()
    history.append(_record("EXEC-002", attempt=2))
    history.append(_record("EXEC-001", attempt=1))
    history.append(_record("EXEC-003", task_id="TASK-002"))
    assert [item.execution_id for item in history.list_for_task("TASK-001")] == ["EXEC-001", "EXEC-002"]


def test_history_lists_project_records_without_cross_project_leakage():
    history = ExecutionHistory()
    history.append(_record("EXEC-002", project_id="PROJECT-002"))
    history.append(_record("EXEC-001", project_id="PROJECT-001"))
    assert [item.execution_id for item in history.list_for_project("PROJECT-001")] == ["EXEC-001"]


def test_history_latest_attempt_is_explicit():
    history = ExecutionHistory()
    history.append(_record("EXEC-001", attempt=1))
    history.append(_record("EXEC-002", attempt=2))
    assert history.latest_attempt("TASK-001") == history.get("EXEC-002")


def test_history_latest_attempt_for_unknown_task_is_none():
    assert ExecutionHistory().latest_attempt("MISSING") is None


def test_history_exposes_snapshot_not_mutable_internal_collection():
    history = ExecutionHistory()
    history.append(_record("EXEC-001"))
    records = history.list_for_task("TASK-001")
    records.clear()
    assert history.list_for_task("TASK-001")


def test_history_does_not_change_task_lifecycle_state():
    history = ExecutionHistory()
    record = _record("EXEC-001")
    history.append(record)
    assert not hasattr(history, "task_manager")
    assert not hasattr(history, "workflow")
    assert not hasattr(history, "router")


def test_history_can_list_empty_task_and_project():
    history = ExecutionHistory()
    assert history.list_for_task("MISSING") == []
    assert history.list_for_project("MISSING") == []
