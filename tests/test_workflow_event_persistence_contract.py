from __future__ import annotations

import json

import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventConflictError
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


def event(event_id="EVENT-001", *, payload=None):
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.completed",
        project_id="PROJECT-001",
        occurred_at="2026-08-22T10:00:00Z",
        task_id="TASK-001",
        payload={} if payload is None else payload,
    )


def test_event_persistence_round_trip(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    item = event()
    adapter.save(item)
    assert adapter.load("EVENT-001") == item
    assert adapter.list_ids() == ["EVENT-001"]


def test_event_persistence_duplicate_is_idempotent_and_conflict_is_rejected(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    item = event()
    adapter.save(item)

    assert adapter.save_if_absent(item) is False
    with pytest.raises(WorkflowEventConflictError):
        adapter.save_if_absent(event(payload={"changed": True}))


def test_event_persistence_batch_rejects_conflict_before_writing(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    adapter.save(event("EVENT-001"))

    with pytest.raises(WorkflowEventConflictError):
        adapter.save_if_absent_many(
            [event("EVENT-002"), event("EVENT-001", payload={"changed": True})]
        )

    assert adapter.list_ids() == ["EVENT-001"]
    with pytest.raises(KeyError):
        adapter.load("EVENT-002")


def test_event_persistence_rejects_corrupt_payload(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    (tmp_path / "EVENT-001.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid workflow event"):
        adapter.load("EVENT-001")


def test_event_persistence_rejects_filename_identity_mismatch(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    payload = event("EVENT-002").to_dict()
    (tmp_path / "EVENT-001.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="identity"):
        adapter.load("EVENT-001")


def test_event_persistence_list_and_delete_ignore_unrelated_entries(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    adapter.save(event())
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "ignored.json").mkdir()

    assert adapter.list_ids() == ["EVENT-001"]
    adapter.delete("EVENT-001")
    assert adapter.list_ids() == []
    assert (tmp_path / "notes.txt").exists()


def test_event_persistence_event_id_is_path_safe(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    with pytest.raises(ValueError):
        adapter.save(event("../EVENT-001"))
