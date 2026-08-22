from __future__ import annotations

from pathlib import Path

import pytest

from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


PROJECT_ID = "PROJECT-FAILURE-001"


def _event(event_id: str, occurred_at: str = "2026-08-22T12:00:00Z") -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type="task_started",
        project_id=PROJECT_ID,
        task_id="TASK-001",
        occurred_at=occurred_at,
        payload={"status": "running"},
    )


def _manager(status: str = "ready") -> TaskManager:
    return TaskManager(
        [
            Task(
                id="TASK-001",
                title="failure injection",
                description="failure boundary",
                role="developer",
                status=status,
                result={"message": "done"} if status == "completed" else None,
            )
        ]
    )


def _plan() -> dict:
    return {
        "project": "failure-injection",
        "summary": "failure boundary contract",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "failure injection",
                "description": "failure boundary",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def _result(manager: TaskManager) -> ProjectResult:
    return ProjectResult.from_task_manager(manager, project="failure-injection")


def test_event_log_does_not_publish_event_when_durable_sink_fails():
    class FailingSink:
        def save_if_absent(self, event: WorkflowEvent) -> bool:
            raise OSError("durable event store unavailable")

    log = WorkflowEventLog(persistence_sink=FailingSink())
    event = _event("EVENT-FAIL-001")

    with pytest.raises(OSError, match="durable event store unavailable"):
        log.append(event)

    assert len(log) == 0
    assert log.list_for_task("TASK-001") == []


def test_event_log_batch_failure_does_not_publish_partial_events(tmp_path, monkeypatch):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    events = [_event("EVENT-FAIL-001"), _event("EVENT-FAIL-002", "2026-08-22T12:01:00Z")]
    real_replace = __import__("os").replace
    calls = 0

    def failing_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("replace failed")
        return real_replace(source, target)

    monkeypatch.setattr("runtime.workflow_event_persistence.os.replace", failing_replace)

    with pytest.raises(OSError, match="replace failed"):
        adapter.save_if_absent_many(events)

    assert adapter.list_ids() == []
    assert [path for path in adapter.root.iterdir() if path.name.endswith(".tmp")] == []


def test_project_update_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    initial = _manager("ready")
    adapter.save(PROJECT_ID, plan=_plan(), task_manager=initial, result=_result(initial))
    before = (tmp_path / "projects" / f"{PROJECT_ID}.json").read_bytes()

    updated = _manager("completed")
    real_replace = __import__("os").replace

    def failing_replace(source, target):
        raise OSError("checkpoint replace failed")

    monkeypatch.setattr("runtime.project_persistence.os.replace", failing_replace)

    with pytest.raises(OSError, match="checkpoint replace failed"):
        adapter.update(PROJECT_ID, plan=_plan(), task_manager=updated, result=_result(updated))

    path = tmp_path / "projects" / f"{PROJECT_ID}.json"
    assert path.read_bytes() == before
    assert adapter.load(PROJECT_ID).task_manager.get_task("TASK-001").status == "ready"

    # Restore the real operation so this test also documents that the adapter
    # remains usable after the injected failure.
    monkeypatch.setattr("runtime.project_persistence.os.replace", real_replace)
    adapter.update(PROJECT_ID, plan=_plan(), task_manager=updated, result=_result(updated))
    assert adapter.load(PROJECT_ID).task_manager.get_task("TASK-001").status == "completed"


def test_project_save_failure_leaves_no_snapshot_or_temp_file(tmp_path, monkeypatch):
    adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    manager = _manager("ready")

    def failing_replace(source, target):
        raise OSError("initial save replace failed")

    monkeypatch.setattr("runtime.project_persistence.os.replace", failing_replace)

    with pytest.raises(OSError, match="initial save replace failed"):
        adapter.save(PROJECT_ID, plan=_plan(), task_manager=manager, result=_result(manager))

    assert adapter.list_ids() == []
    assert [path for path in adapter.root.iterdir() if path.name.endswith(".tmp")] == []


def test_event_log_batch_failure_preserves_preexisting_events(tmp_path, monkeypatch):
    adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    existing = _event("EVENT-FAIL-000")
    adapter.save(existing)
    incoming = [_event("EVENT-FAIL-001"), _event("EVENT-FAIL-002", "2026-08-22T12:01:00Z")]
    real_replace = __import__("os").replace
    calls = 0

    def failing_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("batch replace failed")
        return real_replace(source, target)

    monkeypatch.setattr("runtime.workflow_event_persistence.os.replace", failing_replace)

    with pytest.raises(OSError, match="batch replace failed"):
        adapter.save_if_absent_many(incoming)

    assert adapter.list_ids() == ["EVENT-FAIL-000"]
    assert adapter.load("EVENT-FAIL-000") == existing
