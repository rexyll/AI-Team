from __future__ import annotations

from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.project_result import ProjectResult
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-E2E-001"
TASK_ID = "TASK-E2E-001"


def _event(event_id: str, event_type: str, occurred_at: str, *, payload=None) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=PROJECT_ID,
        task_id=TASK_ID,
        occurred_at=occurred_at,
        payload=payload or {},
    )


def _lifecycle_events() -> list[WorkflowEvent]:
    return [
        _event("EVENT-001", "task_started", "2026-08-22T10:00:00Z", payload={"status": "running"}),
        _event("EVENT-002", "developer_completed", "2026-08-22T10:01:00Z", payload={"status": "completed"}),
        _event("EVENT-003", "tester_skipped", "2026-08-22T10:02:00Z", payload={"status": "skipped"}),
        _event("EVENT-004", "review_started", "2026-08-22T10:03:00Z", payload={"status": "reviewing"}),
        _event("EVENT-005", "reviewer_approved", "2026-08-22T10:04:00Z", payload={"status": "completed"}),
    ]


def _save_project(adapter: ProjectPersistenceAdapter) -> ProjectResult:
    task = Task(
        id=TASK_ID,
        title="end-to-end contract",
        description="cross-boundary contract",
        role="developer",
        status="completed",
        result={"message": "done"},
    )
    manager = TaskManager([task])
    plan = {
        "project": "e2e-contract",
        "summary": "cross-boundary workflow event contract",
        "tasks": [
            {
                "id": TASK_ID,
                "title": task.title,
                "description": task.description,
                "role": task.role,
                "dependencies": [],
            }
        ],
    }
    result = ProjectResult.from_task_manager(manager, project="e2e-contract")
    adapter.save(PROJECT_ID, plan=plan, task_manager=manager, result=result)
    return result


def test_persisted_rehydration_projection_and_query_are_semantically_equivalent(tmp_path):
    project_adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    _save_project(project_adapter)

    events = _lifecycle_events()
    # Deliberately persist in reverse chronological order; query semantics must
    # remain deterministic after filesystem rehydration.
    event_adapter.save_if_absent_many(reversed(events))

    memory_log = WorkflowEventLog()
    memory_log.merge(events)
    memory_query = WorkflowEventQueryService.from_log(memory_log, project_id=PROJECT_ID)
    persisted_query = WorkflowEventQueryService.from_persistence(
        event_adapter,
        project_id=PROJECT_ID,
    )
    recovered_query = WorkflowEventQueryService.from_persisted_project(
        project_adapter,
        event_adapter,
        project_id=PROJECT_ID,
    )

    assert memory_query.as_dict() == persisted_query.as_dict() == recovered_query.as_dict()
    assert persisted_query.lifecycle() == "completed"
    assert persisted_query.lifecycle(TASK_ID) == "completed"
    assert persisted_query.last_event == ("EVENT-005", "reviewer_approved", "2026-08-22T10:04:00Z")
    assert persisted_query.review_status(TASK_ID) == "approved"
    assert persisted_query.retry(TASK_ID) == {"retry_attempt": 0, "max_retries": 0}
    assert persisted_query.error(TASK_ID) is None


def test_retry_failure_revision_and_approval_survive_rehydration_without_write_side_effects(tmp_path):
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    events = [
        _event("EVENT-101", "task_started", "2026-08-22T11:00:00Z", payload={"status": "running"}),
        _event("EVENT-102", "developer_failed", "2026-08-22T11:01:00Z", payload={"status": "failed", "error": "temporary"}),
        _event("EVENT-103", "task_retrying", "2026-08-22T11:02:00Z", payload={"retry_attempt": 1, "max_retries": 2}),
        _event("EVENT-104", "task_started", "2026-08-22T11:03:00Z", payload={"status": "running"}),
        _event("EVENT-105", "review_started", "2026-08-22T11:04:00Z", payload={"status": "reviewing"}),
        _event("EVENT-106", "reviewer_revision", "2026-08-22T11:05:00Z", payload={"status": "revision", "message": "add tests"}),
        _event("EVENT-107", "reviewer_approved", "2026-08-22T11:06:00Z", payload={"status": "completed"}),
    ]
    event_adapter.save_if_absent_many(events)
    before = sorted(path.name for path in event_adapter.root.iterdir())

    service = WorkflowEventQueryService.from_persistence(event_adapter, project_id=PROJECT_ID)

    assert service.lifecycle(TASK_ID) == "completed"
    assert service.retry(TASK_ID) == {"retry_attempt": 1, "max_retries": 2}
    assert service.error(TASK_ID) == "temporary"
    assert service.review_status(TASK_ID) == "approved"
    assert service.last_event[0] == "EVENT-107"
    assert sorted(path.name for path in event_adapter.root.iterdir()) == before


def test_query_snapshot_is_detached_from_rehydrated_event_store(tmp_path):
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    event_adapter.save_if_absent_many(_lifecycle_events())

    service = WorkflowEventQueryService.from_persistence(event_adapter, project_id=PROJECT_ID)
    snapshot = service.as_dict()
    snapshot["tasks"][0]["lifecycle_status"] = "tampered"
    snapshot["tasks"].append({"task_id": "INJECTED"})

    fresh = service.as_dict()
    assert fresh["tasks"] != snapshot["tasks"]
    assert fresh["tasks"][0]["lifecycle_status"] == "completed"
    assert [event.event_id for event in event_adapter.load_log().list_all()] == [
        "EVENT-001",
        "EVENT-002",
        "EVENT-003",
        "EVENT-004",
        "EVENT-005",
    ]
