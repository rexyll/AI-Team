from __future__ import annotations

from pathlib import Path

import pytest

from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-QUERY-001"
TASK_ID = "TASK-QUERY-001"


def _project_adapter(tmp_path: Path) -> ProjectPersistenceAdapter:
    adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    task = Task(
        id=TASK_ID,
        title="query task",
        description="query task",
        role="developer",
        status="completed",
    )
    adapter.save(
        PROJECT_ID,
        plan={
            "project": "query-demo",
            "summary": "query integration",
            "tasks": [task.to_dict()],
        },
        task_manager=TaskManager([task]),
        result=ProjectResult.from_task_manager(TaskManager([task]), project="query-demo"),
    )
    return adapter


def _events(project_id: str = PROJECT_ID) -> list[WorkflowEvent]:
    return [
        WorkflowEvent(
            event_id="EVENT-001",
            event_type="task_started",
            project_id=project_id,
            task_id=TASK_ID,
            occurred_at="2026-08-22T10:00:00Z",
            payload={"status": "running"},
        ),
        WorkflowEvent(
            event_id="EVENT-002",
            event_type="developer_completed",
            project_id=project_id,
            task_id=TASK_ID,
            occurred_at="2026-08-22T10:01:00Z",
            payload={"status": "completed"},
        ),
        WorkflowEvent(
            event_id="EVENT-003",
            event_type="review_started",
            project_id=project_id,
            task_id=TASK_ID,
            occurred_at="2026-08-22T10:02:00Z",
            payload={"status": "reviewing"},
        ),
        WorkflowEvent(
            event_id="EVENT-004",
            event_type="reviewer_approved",
            project_id=project_id,
            task_id=TASK_ID,
            occurred_at="2026-08-22T10:03:00Z",
            payload={"status": "completed"},
        ),
    ]


def test_persisted_project_query_rehydrates_projection_without_runtime_state_exposure(tmp_path):
    project_adapter = _project_adapter(tmp_path)
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    event_adapter.save_if_absent_many(_events())

    query = WorkflowEventQueryService.from_persisted_project(
        project_adapter,
        event_adapter,
        project_id=PROJECT_ID,
    )

    assert query.project_id == PROJECT_ID
    assert query.lifecycle() == "completed"
    assert query.lifecycle(TASK_ID) == "completed"
    assert query.review_status(TASK_ID) == "approved"
    assert query.retry(TASK_ID) == {"retry_attempt": 0, "max_retries": None}
    assert query.error(TASK_ID) is None
    assert query.last_event == ("EVENT-004", "reviewer_approved", "2026-08-22T10:03:00Z")


def test_query_boundary_is_read_only_and_detached(tmp_path):
    project_adapter = _project_adapter(tmp_path)
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    event_adapter.save_if_absent_many(_events())
    project_files_before = sorted(path.name for path in project_adapter.root.iterdir())
    event_files_before = sorted(path.name for path in event_adapter.root.iterdir())

    query = WorkflowEventQueryService.from_persisted_project(
        project_adapter,
        event_adapter,
        project_id=PROJECT_ID,
    )
    diagnostic = query.as_dict()
    diagnostic["tasks"][0]["lifecycle_status"] = "mutated"

    assert query.lifecycle(TASK_ID) == "completed"
    assert sorted(path.name for path in project_adapter.root.iterdir()) == project_files_before
    assert sorted(path.name for path in event_adapter.root.iterdir()) == event_files_before


def test_empty_event_stream_is_legacy_compatible(tmp_path):
    project_adapter = _project_adapter(tmp_path)
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")

    query = WorkflowEventQueryService.from_persisted_project(
        project_adapter,
        event_adapter,
        project_id=PROJECT_ID,
    )

    assert query.project_id == PROJECT_ID
    assert query.lifecycle_status == "unknown"
    assert query.last_event == (None, None, None)
    assert query.projection.tasks == ()


def test_missing_project_snapshot_fails_before_projection(tmp_path):
    project_adapter = ProjectPersistenceAdapter(tmp_path / "projects")
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    event_adapter.save_if_absent(_events()[0])

    with pytest.raises(KeyError):
        WorkflowEventQueryService.from_persisted_project(
            project_adapter,
            event_adapter,
            project_id=PROJECT_ID,
        )


def test_event_stream_identity_mismatch_fails_fast(tmp_path):
    project_adapter = _project_adapter(tmp_path)
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    event_adapter.save_if_absent(_events(project_id="PROJECT-OTHER")[0])

    with pytest.raises(ValueError, match="no events for project"):
        WorkflowEventQueryService.from_persisted_project(
            project_adapter,
            event_adapter,
            project_id=PROJECT_ID,
        )


def test_corrupt_persisted_event_fails_fast(tmp_path):
    project_adapter = _project_adapter(tmp_path)
    event_adapter = WorkflowEventPersistenceAdapter(tmp_path / "events")
    (event_adapter.root / "EVENT-CORRUPT.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid workflow event"):
        WorkflowEventQueryService.from_persisted_project(
            project_adapter,
            event_adapter,
            project_id=PROJECT_ID,
        )
