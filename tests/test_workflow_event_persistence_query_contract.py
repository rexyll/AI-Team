from __future__ import annotations

import json

import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


def event(
    event_id: str,
    *,
    project_id: str = "PROJECT-001",
    task_id: str | None = "TASK-001",
    occurred_at: str = "2026-08-22T10:00:00Z",
) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.completed",
        project_id=project_id,
        occurred_at=occurred_at,
        task_id=task_id,
        payload={"event_id": event_id},
    )


def test_persistence_list_all_matches_in_memory_global_order(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    log = WorkflowEventLog()
    events = [
        event("EVENT-003", project_id="PROJECT-002", task_id="TASK-001"),
        event("EVENT-002", project_id="PROJECT-001", task_id="TASK-002"),
        event("EVENT-001", project_id="PROJECT-001", task_id="TASK-001"),
        event("EVENT-004", project_id="PROJECT-001", task_id=None),
    ]
    log.merge(events)
    adapter.save_if_absent_many(events)

    assert adapter.list_all() == log.list_all()


def test_persistence_project_query_matches_in_memory_project_order(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    log = WorkflowEventLog()
    events = [
        event("EVENT-003", occurred_at="2026-08-22T10:02:00Z"),
        event("EVENT-001", occurred_at="2026-08-22T10:01:00Z"),
        event("EVENT-002", project_id="PROJECT-002"),
        event("EVENT-004", occurred_at="2026-08-22T10:01:00Z"),
    ]
    log.merge(events)
    adapter.save_if_absent_many(events)

    assert adapter.list_for_project("PROJECT-001") == log.list_for_project("PROJECT-001")
    assert adapter.list_for_project("PROJECT-002") == log.list_for_project("PROJECT-002")


def test_persistence_task_query_matches_in_memory_task_order(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    log = WorkflowEventLog()
    events = [
        event("EVENT-003", task_id="TASK-002", occurred_at="2026-08-22T10:03:00Z"),
        event("EVENT-001", task_id="TASK-001", occurred_at="2026-08-22T10:02:00Z"),
        event("EVENT-002", task_id="TASK-001", occurred_at="2026-08-22T10:01:00Z"),
    ]
    log.merge(events)
    adapter.save_if_absent_many(events)

    assert adapter.list_for_task("TASK-001") == log.list_for_task("TASK-001")
    assert adapter.list_for_task("TASK-002") == log.list_for_task("TASK-002")


def test_persistence_queries_return_empty_for_unknown_scope(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    adapter.save(event("EVENT-001"))

    assert adapter.list_all()
    assert adapter.list_for_project("PROJECT-404") == []
    assert adapter.list_for_task("TASK-404") == []


def test_persistence_query_fails_fast_on_corrupt_event(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    adapter.save(event("EVENT-001"))
    (tmp_path / "EVENT-002.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid workflow event"):
        adapter.list_all()
    with pytest.raises(ValueError, match="invalid workflow event"):
        adapter.list_for_project("PROJECT-001")
    with pytest.raises(ValueError, match="invalid workflow event"):
        adapter.list_for_task("TASK-001")


def test_persistence_query_uses_event_id_as_same_timestamp_tiebreaker(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    items = [
        event("EVENT-B", occurred_at="2026-08-22T10:00:00Z"),
        event("EVENT-A", occurred_at="2026-08-22T10:00:00Z"),
    ]
    adapter.save_if_absent_many(items)

    assert [item.event_id for item in adapter.list_for_project("PROJECT-001")] == [
        "EVENT-A",
        "EVENT-B",
    ]
