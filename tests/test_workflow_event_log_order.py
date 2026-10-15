from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


def _event(event_id: str, event_type: str, occurred_at: str = "2026-08-26T00:00:00Z") -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id="PROJECT-1",
        task_id="TASK-1",
        occurred_at=occurred_at,
        payload={},
    )


def test_list_for_task_preserves_append_order_when_timestamps_are_identical():
    log = WorkflowEventLog()
    events = [
        _event("z-event", "task_started"),
        _event("a-event", "developer_completed"),
        _event("y-event", "tester_skipped"),
        _event("b-event", "review_started"),
        _event("x-event", "reviewer_approved"),
    ]

    for event in events:
        log.append(event)

    assert [event.event_type for event in log.list_for_task("TASK-1")] == [
        "task_started",
        "developer_completed",
        "tester_skipped",
        "review_started",
        "reviewer_approved",
    ]
