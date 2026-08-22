from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.agent_router import AgentRouter
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter

PLAN = {"project": "event-recovery-demo", "summary": "event recovery", "tasks": [{"id": "TASK-001", "title": "done", "description": "already done", "role": "architect", "dependencies": []}]}


def _manager() -> TaskManager:
    return TaskManager([Task(id="TASK-001", title="done", description="already done", role="architect", status="completed", result={"status": "completed"})])


def _event(event_id: str, occurred_at: str) -> WorkflowEvent:
    return WorkflowEvent(event_id=event_id, event_type="task_started", project_id="PROJECT-001", task_id="TASK-001", occurred_at=occurred_at, payload={"source": "test"})


def _save_project(adapter: ProjectPersistenceAdapter) -> ProjectResult:
    manager = _manager()
    result = ProjectResult.from_task_manager(manager, project="event-recovery-demo")
    adapter.save("PROJECT-001", plan=PLAN, task_manager=manager, result=result)
    return result


def test_resume_persisted_rehydrates_independent_event_log(tmp_path):
    project_adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    result = _save_project(project_adapter)
    event_adapter.save_if_absent_many([_event("EVENT-002", "2026-08-22T10:01:00Z"), _event("EVENT-001", "2026-08-22T10:00:00Z")])

    project = ProjectOrchestrator(agent_router=AgentRouter())
    assert project.resume_persisted("PROJECT-001", project_adapter, event_persistence=event_adapter) == result
    assert project.workflow_event_log is not None
    assert [event.event_id for event in project.workflow_event_log.list_all()[:2]] == ["EVENT-001", "EVENT-002"]
    assert project.workflow_event_log.list_for_project("PROJECT-001")[-1].event_type == "project.resumed"
    assert [event.event_id for event in event_adapter.list_all()] == ["EVENT-001", "EVENT-002"]


def test_project_snapshot_does_not_embed_workflow_events(tmp_path):
    project_adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    _save_project(project_adapter)
    event_adapter.save(_event("EVENT-001", "2026-08-22T10:00:00Z"))
    ProjectOrchestrator(agent_router=AgentRouter()).resume_persisted("PROJECT-001", project_adapter, event_persistence=event_adapter)
    payload = (tmp_path / "projects" / "PROJECT-001.json").read_text(encoding="utf-8")
    assert "workflow_event" not in payload
    assert "EVENT-001" not in payload


def test_resume_without_event_adapter_keeps_legacy_behavior(tmp_path):
    project_adapter = ProjectPersistenceAdapter(tmp_path)
    result = _save_project(project_adapter)
    project = ProjectOrchestrator(agent_router=AgentRouter())
    assert project.resume_persisted("PROJECT-001", project_adapter) == result
    assert project.workflow_event_log is None


def test_event_rehydration_failure_is_not_swallowed(tmp_path):
    project_adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    _save_project(project_adapter)
    (tmp_path / "events" / "EVENT-001.json").write_text("{broken", encoding="utf-8")
    try:
        ProjectOrchestrator(agent_router=AgentRouter()).resume_persisted("PROJECT-001", project_adapter, event_persistence=event_adapter)
    except ValueError as exc:
        assert "invalid workflow event" in str(exc)
    else:
        raise AssertionError("corrupt event recovery must fail fast")
