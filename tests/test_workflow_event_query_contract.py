from __future__ import annotations

from pathlib import Path

import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-CONTRACT-001"
TASK_ID = "TASK-CONTRACT-001"


def _event(
    event_id: str,
    event_type: str,
    occurred_at: str,
    payload: dict,
    *,
    task_id: str | None = TASK_ID,
    project_id: str = PROJECT_ID,
) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=project_id,
        task_id=task_id,
        occurred_at=occurred_at,
        payload=payload,
    )


def _complete_events() -> list[WorkflowEvent]:
    return [
        _event("EVENT-001", "task_started", "2026-08-22T10:00:00Z", {"status": "running"}),
        _event("EVENT-002", "developer_completed", "2026-08-22T10:01:00Z", {"status": "completed"}),
        _event("EVENT-003", "review_started", "2026-08-22T10:02:00Z", {"status": "reviewing"}),
        _event("EVENT-004", "reviewer_approved", "2026-08-22T10:03:00Z", {"status": "completed"}),
    ]


def test_query_rejects_invalid_log_and_persistence_inputs():
    with pytest.raises(TypeError, match="event_log"):
        WorkflowEventQueryService.from_log(object(), project_id=PROJECT_ID)
    with pytest.raises(TypeError, match="persistence"):
        WorkflowEventQueryService.from_persistence(object(), project_id=PROJECT_ID)


def test_query_rejects_invalid_project_id():
    log = WorkflowEventLog()
    with pytest.raises(ValueError, match="project_id"):
        WorkflowEventQueryService.from_log(log, project_id=" ")


def test_partial_lifecycle_has_deterministic_task_and_project_status():
    query = WorkflowEventQueryService.from_log(
        WorkflowEventLog(_complete_events()[:2]),
        project_id=PROJECT_ID,
    )

    assert query.lifecycle() == "running"
    assert query.lifecycle(TASK_ID) == "review_pending"
    assert query.review_status(TASK_ID) is None
    assert query.last_event == ("EVENT-002", "developer_completed", "2026-08-22T10:01:00Z")


def test_unknown_event_type_is_forward_compatible_and_preserves_last_event():
    events = _complete_events()[:2] + [
        _event("EVENT-003", "future.workflow.event", "2026-08-22T10:02:00Z", {"future": True}),
    ]
    query = WorkflowEventQueryService.from_log(WorkflowEventLog(events), project_id=PROJECT_ID)

    assert query.lifecycle(TASK_ID) == "review_pending"
    assert query.last_event == ("EVENT-003", "future.workflow.event", "2026-08-22T10:02:00Z")


def test_retry_failure_revision_approval_matrix_is_projected_deterministically():
    events = [
        _event("EVENT-001", "task_started", "2026-08-22T10:00:00Z", {"status": "running"}),
        _event("EVENT-002", "developer_failed", "2026-08-22T10:01:00Z", {"status": "failed", "error": "temporary"}),
        _event(
            "EVENT-003",
            "task_retrying",
            "2026-08-22T10:02:00Z",
            {"status": "ready", "retry_attempt": 1, "max_retries": 2, "reason": "temporary"},
        ),
        _event("EVENT-004", "task_started", "2026-08-22T10:03:00Z", {"status": "running"}),
        _event("EVENT-005", "developer_completed", "2026-08-22T10:04:00Z", {"status": "completed"}),
        _event("EVENT-006", "review_started", "2026-08-22T10:05:00Z", {"status": "reviewing"}),
        _event("EVENT-007", "reviewer_revision", "2026-08-22T10:06:00Z", {"status": "revision"}),
        _event("EVENT-008", "task_started", "2026-08-22T10:07:00Z", {"status": "running"}),
        _event("EVENT-009", "developer_completed", "2026-08-22T10:08:00Z", {"status": "completed"}),
        _event("EVENT-010", "review_started", "2026-08-22T10:09:00Z", {"status": "reviewing"}),
        _event("EVENT-011", "reviewer_approved", "2026-08-22T10:10:00Z", {"status": "completed"}),
    ]
    query = WorkflowEventQueryService.from_log(WorkflowEventLog(events), project_id=PROJECT_ID)

    assert query.lifecycle(TASK_ID) == "completed"
    assert query.retry(TASK_ID) == {"retry_attempt": 1, "max_retries": 2}
    assert query.error(TASK_ID) == "temporary"
    assert query.review_status(TASK_ID) == "approved"
    assert query.last_event[0] == "EVENT-011"


def test_unknown_task_is_a_stable_key_error():
    query = WorkflowEventQueryService.from_log(WorkflowEventLog(_complete_events()), project_id=PROJECT_ID)
    with pytest.raises(KeyError):
        query.task("TASK-MISSING")
    with pytest.raises(KeyError):
        query.lifecycle("TASK-MISSING")


def test_malformed_known_event_fails_fast_with_event_identity():
    malformed = _event(
        "EVENT-BAD",
        "reviewer_approved",
        "2026-08-22T10:00:00Z",
        {"status": "approved"},
    )
    with pytest.raises(ValueError, match="EVENT-BAD"):
        WorkflowEventQueryService.from_log(WorkflowEventLog([malformed]), project_id=PROJECT_ID)


def test_log_and_persistence_sources_have_identical_query_results(tmp_path: Path):
    events = list(reversed(_complete_events()))
    log_query = WorkflowEventQueryService.from_log(WorkflowEventLog(events), project_id=PROJECT_ID)

    persistence = WorkflowEventPersistenceAdapter(tmp_path / "events")
    persistence.save_if_absent_many(events)
    persisted_query = WorkflowEventQueryService.from_persistence(persistence, project_id=PROJECT_ID)

    assert persisted_query.as_dict() == log_query.as_dict()


def test_query_isolated_from_source_log_after_construction():
    log = WorkflowEventLog(_complete_events())
    query = WorkflowEventQueryService.from_log(log, project_id=PROJECT_ID)

    log.append(_event("EVENT-005", "task_failed", "2026-08-22T10:04:00Z", {"status": "failed", "error": "late"}))

    assert query.lifecycle(TASK_ID) == "completed"
    assert query.last_event[0] == "EVENT-004"


def test_as_dict_is_detached_at_nested_levels():
    query = WorkflowEventQueryService.from_log(WorkflowEventLog(_complete_events()), project_id=PROJECT_ID)
    first = query.as_dict()
    first["tasks"].append({"task_id": "MUTATED"})
    first["tasks"][0]["review_status"] = "mutated"

    second = query.as_dict()
    assert len(second["tasks"]) == 1
    assert second["tasks"][0]["review_status"] == "approved"
