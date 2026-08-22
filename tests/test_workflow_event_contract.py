from __future__ import annotations

import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventConflictError, WorkflowEventLog


def event(event_id="EVENT-001", *, occurred_at="2026-08-22T10:00:00Z", task_id="TASK-001", payload=None):
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.completed",
        project_id="PROJECT-001",
        occurred_at=occurred_at,
        task_id=task_id,
        payload={} if payload is None else payload,
    )


def test_workflow_event_is_immutable_and_json_friendly():
    value = {"nested": [1, 2]}
    item = event(payload=value)
    value["nested"].append(3)

    assert item.payload == {"nested": [1, 2]}
    with pytest.raises((AttributeError, TypeError)):
        item.event_type = "task.failed"
    assert item.to_dict() == {
        "event_id": "EVENT-001",
        "event_type": "task.completed",
        "project_id": "PROJECT-001",
        "occurred_at": "2026-08-22T10:00:00Z",
        "task_id": "TASK-001",
        "payload": {"nested": [1, 2]},
    }


def test_workflow_event_requires_json_object_payload():
    with pytest.raises(TypeError, match="payload"):
        WorkflowEvent(
            event_id="EVENT-001",
            event_type="task.completed",
            project_id="PROJECT-001",
            occurred_at="2026-08-22T10:00:00Z",
            payload={"bad": object()},
        )


def test_workflow_event_round_trip():
    item = event()
    assert WorkflowEvent.from_dict(item.to_dict()) == item


def test_event_log_append_rejects_duplicate_and_is_idempotent_when_requested():
    log = WorkflowEventLog()
    item = event()
    log.append(item)
    with pytest.raises(ValueError, match="event_id already exists"):
        log.append(item)
    assert log.append_if_absent(item) is False
    assert len(log) == 1


def test_event_log_rejects_conflicting_event_id():
    log = WorkflowEventLog()
    log.append(event())
    conflicting = event(payload={"changed": True})
    with pytest.raises(WorkflowEventConflictError, match="EVENT-001"):
        log.append_if_absent(conflicting)


def test_event_log_merge_is_atomic_on_conflict():
    log = WorkflowEventLog()
    log.append(event("EVENT-001"))
    incoming = [event("EVENT-002"), event("EVENT-001", payload={"changed": True})]

    with pytest.raises(WorkflowEventConflictError):
        log.merge(incoming)

    assert len(log) == 1
    with pytest.raises(KeyError):
        log.get("EVENT-002")


def test_event_log_queries_have_deterministic_order():
    log = WorkflowEventLog()
    log.merge(
        [
            event("EVENT-003", occurred_at="2026-08-22T10:00:01Z"),
            event("EVENT-001", occurred_at="2026-08-22T10:00:00Z"),
            event("EVENT-002", occurred_at="2026-08-22T10:00:01Z"),
        ]
    )

    assert [item.event_id for item in log.list_for_project("PROJECT-001")] == [
        "EVENT-001",
        "EVENT-002",
        "EVENT-003",
    ]
    assert [item.event_id for item in log.list_for_task("TASK-001")] == [
        "EVENT-001",
        "EVENT-002",
        "EVENT-003",
    ]


def test_event_log_from_dict_rejects_conflicting_duplicate_ids():
    first = event("EVENT-001").to_dict()
    second = event("EVENT-001", payload={"changed": True}).to_dict()
    with pytest.raises(WorkflowEventConflictError):
        WorkflowEventLog.from_dict([first, second])
