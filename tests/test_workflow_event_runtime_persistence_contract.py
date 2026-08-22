from __future__ import annotations

import pytest

from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_router import AgentRouter
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventConflictError, WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


def _event(event_id: str = "EVENT-001") -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type="task_started",
        project_id="PROJECT-001",
        task_id="TASK-001",
        occurred_at="2026-08-22T10:00:00Z",
        payload={"source": "test"},
    )


def test_runtime_sink_persists_new_events_and_keeps_in_memory_log(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    log = WorkflowEventLog(persistence_sink=adapter)

    log.append(_event())

    assert log.get("EVENT-001") == _event()
    assert adapter.load("EVENT-001") == _event()


def test_runtime_sink_is_optional_for_legacy_in_memory_callers():
    log = WorkflowEventLog()

    log.append(_event())

    assert log.list_all() == [_event()]


def test_runtime_sink_failure_is_visible_and_does_not_publish_to_memory():
    class FailingSink:
        def save_if_absent(self, event: WorkflowEvent) -> bool:
            raise OSError("durable event store unavailable")

    log = WorkflowEventLog(persistence_sink=FailingSink())

    with pytest.raises(OSError, match="durable event store unavailable"):
        log.append(_event())

    assert len(log) == 0


def test_runtime_sink_reuses_idempotent_and_conflict_semantics(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    adapter.save(_event())

    log = WorkflowEventLog(persistence_sink=adapter)
    assert log.append_if_absent(_event()) is True
    assert len(log) == 1

    conflicting = WorkflowEvent(
        event_id="EVENT-001",
        event_type="task_completed",
        project_id="PROJECT-001",
        task_id="TASK-001",
        occurred_at="2026-08-22T10:00:01Z",
        payload={"source": "changed"},
    )
    with pytest.raises(WorkflowEventConflictError):
        WorkflowEventLog(persistence_sink=adapter).append(conflicting)


def test_project_orchestrator_can_create_runtime_persisted_event_log(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    project = ProjectOrchestrator(
        agent_router=AgentRouter(),
        project_id="PROJECT-001",
        workflow_event_persistence=adapter,
    )
    manager = TaskManager(
        [
            Task(
                id="TASK-001",
                title="done",
                description="already done",
                role="architect",
                status="completed",
            )
        ]
    )

    project.resume(manager)

    assert project.workflow_event_log is not None
    persisted = adapter.list_all()
    assert len(persisted) == 1
    assert persisted[0].event_type == "project.resumed"
    assert persisted[0].project_id == "PROJECT-001"


def test_runtime_event_persistence_does_not_write_project_snapshot(tmp_path):
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    project_adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    project = ProjectOrchestrator(
        agent_router=AgentRouter(),
        project_id="PROJECT-001",
        workflow_event_persistence=event_adapter,
    )
    manager = TaskManager(
        [
            Task(
                id="TASK-001",
                title="done",
                description="already done",
                role="architect",
                status="completed",
            )
        ]
    )
    result = project.resume(manager)
    project_adapter.save(
        "PROJECT-001",
        plan={"project": "demo", "summary": "demo", "tasks": []},
        task_manager=manager,
        result=result,
    )

    snapshot = (tmp_path / "projects" / "PROJECT-001.json").read_text(encoding="utf-8")
    assert "workflow_event" not in snapshot
    assert "EVENT-001" not in snapshot
    assert event_adapter.list_all()
