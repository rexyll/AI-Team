from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_projection import replay_workflow_events


def _event(event_id, event_type, occurred_at, payload):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id="PROJECT-RECOVERY-PROJECTION",
        task_id="TASK-RECOVERY-PROJECTION",
        occurred_at=occurred_at,
        payload=payload,
    )


def test_reviewer_fallback_and_retry_are_projected_as_review_lifecycle():
    log = WorkflowEventLog()
    log.merge([
        _event("EVENT-001", "review_started", "2026-08-26T14:00:00Z", {"status": "reviewing"}),
        _event("EVENT-002", "reviewer_fallback", "2026-08-26T14:01:00Z", {"status": "revision"}),
        _event("EVENT-003", "reviewer_retry", "2026-08-26T14:02:00Z", {"attempt": 1, "max_attempts": 1}),
        _event("EVENT-004", "reviewer_approved", "2026-08-26T14:03:00Z", {"status": "completed"}),
    ])

    task = replay_workflow_events(log, project_id="PROJECT-RECOVERY-PROJECTION").task("TASK-RECOVERY-PROJECTION")

    assert task.lifecycle_status == "completed"
    assert task.review_status == "approved"
    assert task.last_event_type == "reviewer_approved"
