import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_projection import (
    WorkflowEventProjector,
    replay_workflow_events,
)


def event(event_id, event_type, *, task_id="TASK-001", occurred_at=None, payload=None):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id="PROJECT-001",
        task_id=task_id,
        occurred_at=occurred_at or f"2026-08-22T10:00:{int(event_id.split('-')[-1]):02d}Z",
        payload=payload or {},
    )


def test_empty_project_stream_is_unknown_and_side_effect_free():
    log = WorkflowEventLog()

    projection = WorkflowEventProjector.project(log, project_id="PROJECT-001")

    assert projection.project_id == "PROJECT-001"
    assert projection.lifecycle_status == "unknown"
    assert projection.tasks == ()
    assert len(log) == 0


def test_normal_task_lifecycle_replays_to_completed():
    events = [
        event("EVENT-001", "task_started"),
        event("EVENT-002", "developer_completed", payload={"status": "completed"}),
        event("EVENT-003", "tester_skipped", payload={"status": "skipped"}),
        event("EVENT-004", "review_started"),
        event("EVENT-005", "reviewer_approved", payload={"status": "completed"}),
    ]

    projection = replay_workflow_events(events)
    task = projection.task("TASK-001")

    assert projection.lifecycle_status == "completed"
    assert task.lifecycle_status == "completed"
    assert task.review_status == "approved"
    assert task.last_event_type == "reviewer_approved"


def test_retry_failure_and_revision_rounds_are_replayed_deterministically():
    events = [
        event("EVENT-001", "task_started", occurred_at="2026-08-22T10:00:00Z"),
        event("EVENT-002", "task_failed", occurred_at="2026-08-22T10:00:01Z", payload={"status": "failed", "error": "temporary"}),
        event(
            "EVENT-003",
            "task_retrying",
            occurred_at="2026-08-22T10:00:02Z",
            payload={"status": "ready", "retry_attempt": 1, "max_retries": 2, "reason": "RuntimeError: temporary"},
        ),
        event("EVENT-004", "task_started", occurred_at="2026-08-22T10:00:03Z"),
        event("EVENT-005", "developer_completed", occurred_at="2026-08-22T10:00:04Z", payload={"status": "completed"}),
        event("EVENT-006", "review_started", occurred_at="2026-08-22T10:00:05Z"),
        event("EVENT-007", "reviewer_revision", occurred_at="2026-08-22T10:00:06Z", payload={"status": "revision"}),
        event("EVENT-008", "task_started", occurred_at="2026-08-22T10:00:07Z"),
        event("EVENT-009", "review_started", occurred_at="2026-08-22T10:00:08Z"),
        event("EVENT-010", "reviewer_approved", occurred_at="2026-08-22T10:00:09Z", payload={"status": "completed"}),
    ]

    projection = replay_workflow_events(reversed(events))
    task = projection.task("TASK-001")

    assert task.lifecycle_status == "completed"
    assert task.retry_attempt == 1
    assert task.max_retries == 2
    assert task.review_status == "approved"
    assert task.last_event_id == "EVENT-010"


def test_project_resumed_is_a_marker_not_a_task_state_transition():
    events = [
        event("EVENT-001", "task_started"),
        event("EVENT-002", "developer_completed", payload={"status": "completed"}),
        event("EVENT-003", "project.resumed", task_id=None),
    ]

    projection = replay_workflow_events(events)

    assert projection.resumed is True
    assert projection.task("TASK-001").lifecycle_status == "review_pending"
    assert projection.last_event_type == "project.resumed"


def test_unknown_event_type_is_forward_compatible():
    events = [
        event("EVENT-001", "task_started"),
        event("EVENT-002", "future.lifecycle.event", payload={"new": "field"}),
        event("EVENT-003", "developer_completed", payload={"status": "completed"}),
    ]

    task = replay_workflow_events(events).task("TASK-001")

    assert task.lifecycle_status == "review_pending"
    assert task.last_event_type == "developer_completed"


def test_malformed_known_event_fails_with_event_identity():
    malformed = event("EVENT-009", "developer_completed", payload={"status": "failed"})

    with pytest.raises(ValueError, match="EVENT-009"):
        replay_workflow_events([malformed])


def test_projection_is_independent_from_event_log_and_does_not_persist(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    log = WorkflowEventLog(persistence_sink=adapter)
    log.append(event("EVENT-001", "task_started"))

    before = adapter.list_all()
    projection = replay_workflow_events(log)
    log.append(event("EVENT-002", "developer_completed", payload={"status": "completed"}))

    assert projection.task("TASK-001").lifecycle_status == "running"
    assert [item.event_id for item in before] == ["EVENT-001"]
    assert [item.event_id for item in adapter.list_all()] == ["EVENT-001", "EVENT-002"]


def test_persisted_stream_can_be_rehydrated_then_projected(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    adapter.save_if_absent_many(
        [
            event("EVENT-002", "developer_completed", payload={"status": "completed"}),
            event("EVENT-001", "task_started"),
            event("EVENT-003", "review_started"),
        ]
    )

    recovered = adapter.load_log()
    projection = WorkflowEventProjector.project(recovered)

    assert [item.event_id for item in recovered.list_for_task("TASK-001")] == [
        "EVENT-001",
        "EVENT-002",
        "EVENT-003",
    ]
    assert projection.task("TASK-001").lifecycle_status == "reviewing"
