from __future__ import annotations

from runtime.execution_history import ExecutionHistory
from runtime.execution_record import AgentExecutionRecord
from runtime.execution_record_persistence import ExecutionRecordPersistenceAdapter


def _record(execution_id: str, attempt: int = 1) -> AgentExecutionRecord:
    return AgentExecutionRecord(
        execution_id=execution_id,
        project_id="PROJECT-001",
        task_id="TASK-001",
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


def test_history_can_be_saved_to_and_loaded_from_persistence(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    history = ExecutionHistory()
    history.append(_record("EXEC-001", 1))
    history.append(_record("EXEC-002", 2))

    history.save(adapter)
    restored = ExecutionHistory.load(adapter)

    assert restored.list_for_task("TASK-001") == history.list_for_task("TASK-001")
    assert restored.latest_attempt("TASK-001") == history.latest_attempt("TASK-001")


def test_history_save_does_not_change_existing_records(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    history = ExecutionHistory()
    record = _record("EXEC-001")
    history.append(record)

    history.save(adapter)

    assert history.get("EXEC-001") is record


def test_loading_empty_persistence_returns_empty_history(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    restored = ExecutionHistory.load(adapter)
    assert restored.list_for_task("MISSING") == []


def test_history_persistence_does_not_require_runtime_orchestration_objects(tmp_path):
    adapter = ExecutionRecordPersistenceAdapter(tmp_path)
    history = ExecutionHistory()
    history.append(_record("EXEC-001"))
    history.save(adapter)

    assert not hasattr(history, "task_manager")
    assert not hasattr(history, "workflow")
    assert not hasattr(history, "router")
