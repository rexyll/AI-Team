from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventConflictError, WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


PROJECT_ID = "PROJECT-CONTENTION-001"
TASK_ID = "TASK-CONTENTION-001"


def event(event_id: str, *, payload: dict | None = None) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.completed",
        project_id=PROJECT_ID,
        occurred_at="2026-08-22T12:00:00Z",
        task_id=TASK_ID,
        payload={} if payload is None else payload,
    )


def test_concurrent_save_if_absent_preserves_one_immutable_record(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    item = event("EVENT-SAME-001")

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _: adapter.save_if_absent(item), range(64)))

    assert sum(results) == 1
    assert adapter.list_ids() == ["EVENT-SAME-001"]
    assert adapter.load("EVENT-SAME-001") == item
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_conflicting_writers_cannot_overwrite_event_identity(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    first = event("EVENT-CONFLICT-001", payload={"writer": "first"})
    second = event("EVENT-CONFLICT-001", payload={"writer": "second"})

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(
            lambda item: _save_result(adapter, item),
            [first, second] * 32,
        ))

    successes = [result for result in results if result == "created"]
    idempotent = [result for result in results if result == "same"]
    conflicts = [result for result in results if result == "conflict"]

    assert len(successes) == 1
    assert len(idempotent) == 31
    assert len(conflicts) == 32
    persisted = adapter.load("EVENT-CONFLICT-001")
    assert persisted in {first, second}
    assert adapter.list_ids() == ["EVENT-CONFLICT-001"]
    assert not list(tmp_path.glob("*.tmp"))


def _save_result(adapter: WorkflowEventPersistenceAdapter, item: WorkflowEvent) -> str:
    try:
        return "created" if adapter.save_if_absent(item) else "same"
    except WorkflowEventConflictError:
        return "conflict"


def test_concurrent_distinct_writers_do_not_drop_successful_events(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    items = [event(f"EVENT-{index:03d}") for index in range(96)]

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(adapter.save_if_absent, items))

    assert all(results)
    assert adapter.list_ids() == [f"EVENT-{index:03d}" for index in range(96)]
    assert [item.event_id for item in adapter.list_all()] == [
        f"EVENT-{index:03d}" for index in range(96)
    ]
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_overlapping_batch_writers_preserve_identity_and_cleanup(tmp_path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    items = [event(f"EVENT-BATCH-{index:03d}") for index in range(24)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        counts = list(executor.map(adapter.save_if_absent_many, [items] * 8))

    assert sum(counts) == len(items)
    assert adapter.list_ids() == [f"EVENT-BATCH-{index:03d}" for index in range(24)]
    assert len(adapter.load_log()) == len(items)
    assert not list(tmp_path.glob("*.tmp"))


def test_persistence_failure_does_not_pollute_in_memory_log():
    class FailingSink:
        def save_if_absent(self, event: WorkflowEvent) -> bool:
            raise OSError("disk unavailable")

    log = WorkflowEventLog(persistence_sink=FailingSink())
    item = event("EVENT-FAIL-001")

    with pytest.raises(OSError, match="disk unavailable"):
        log.append_if_absent(item)

    assert len(log) == 0
    with pytest.raises(KeyError):
        log.get(item.event_id)
