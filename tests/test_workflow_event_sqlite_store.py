from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventConflictError
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_sqlite_store import SqliteWorkflowEventStore


def event(event_id, *, project_id="PROJECT-001", task_id=None, occurred_at="2026-09-07T10:00:00Z", sequence=None):
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.stage_completed",
        project_id=project_id,
        occurred_at=occurred_at,
        task_id=task_id,
        payload={},
        sequence=sequence,
    )


@pytest.fixture(params=["json", "sqlite"])
def store(request, tmp_path):
    if request.param == "json":
        return WorkflowEventPersistenceAdapter(tmp_path / "events")
    return SqliteWorkflowEventStore(tmp_path / "events.db")


def test_save_and_load_round_trip_preserves_sequence(store):
    original = event("E-1", task_id="TASK-1", sequence=3)

    store.save(original)

    restored = store.load("E-1")
    assert restored == original
    assert restored.sequence == 3


def test_save_twice_raises_file_exists_error(store):
    store.save(event("E-1"))

    with pytest.raises(FileExistsError):
        store.save(event("E-1"))


def test_save_if_absent_deduplicates_and_conflicts(store):
    assert store.save_if_absent(event("E-1")) is True
    assert store.save_if_absent(event("E-1")) is False

    conflicting = WorkflowEvent(
        event_id="E-1",
        event_type="task.failed",
        project_id="PROJECT-001",
        occurred_at="2026-09-07T10:00:00Z",
        payload={},
    )
    with pytest.raises(WorkflowEventConflictError):
        store.save_if_absent(conflicting)


def test_save_if_absent_many_counts_created_and_skips_known(store):
    assert store.save_if_absent_many([event("E-1"), event("E-2")]) == 2
    assert store.save_if_absent_many([event("E-2"), event("E-3")]) == 1

    with pytest.raises(WorkflowEventConflictError):
        store.save_if_absent_many(
            [
                event("E-4"),
                WorkflowEvent(
                    event_id="E-1",
                    event_type="task.failed",
                    project_id="PROJECT-001",
                    occurred_at="2026-09-07T10:00:00Z",
                    payload={},
                ),
            ]
        )


def test_load_log_restores_sequences_for_counter_continuation(store):
    store.save_if_absent_many([event("E-1", sequence=1), event("E-2", sequence=2)])

    log = store.load_log()
    log.append(event("E-3"))

    assert log.get("E-3").sequence == 3


def test_missing_event_raises_key_error(store):
    with pytest.raises(KeyError):
        store.load("E-MISSING")
    with pytest.raises(KeyError):
        store.delete("E-MISSING")


def test_query_ordering_matches_adapter_contracts(store):
    store.save_if_absent_many(
        [
            event("E-B", project_id="P-2", occurred_at="2026-09-07T10:00:01Z"),
            event("E-A", project_id="P-1", task_id="T-1", occurred_at="2026-09-07T10:00:02Z"),
            event("E-C", project_id="P-1", occurred_at="2026-09-07T10:00:00Z"),
        ]
    )

    all_ids = [item.event_id for item in store.list_all()]
    # task-scoped events sort before the NULL-task sentinel ('\uffff').
    assert all_ids == ["E-A", "E-C", "E-B"]

    project_ids = [item.event_id for item in store.list_for_project("P-1")]
    assert project_ids == ["E-C", "E-A"]

    task_ids = [item.event_id for item in store.list_for_task("T-1")]
    assert task_ids == ["E-A"]

    assert store.list_ids() == ["E-A", "E-B", "E-C"]

    with pytest.raises(ValueError):
        store.list_for_project("  ")
    with pytest.raises(ValueError):
        store.list_for_task("")


def test_delete_removes_only_target(store):
    store.save_if_absent_many([event("E-1"), event("E-2")])

    store.delete("E-1")

    assert store.list_ids() == ["E-2"]
    with pytest.raises(KeyError):
        store.load("E-1")


def test_concurrent_writers_are_serialized_without_loss(tmp_path):
    store = SqliteWorkflowEventStore(tmp_path / "events.db")
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def write(index: int) -> None:
        try:
            barrier.wait()
            store.save_if_absent(event(f"E-{index:02d}"))
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.count() == 8


def test_corrupt_payload_is_rejected(tmp_path):
    store = SqliteWorkflowEventStore(tmp_path / "events.db")
    store.save(event("E-1"))

    connection = sqlite3.connect(str(tmp_path / "events.db"))
    connection.execute(
        "UPDATE events SET payload = ?", (json.dumps({"event_id": "E-1"}),)
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError):
        store.load("E-1")
