from __future__ import annotations

import threading

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


def event(event_id, *, project_id="PROJECT-001", task_id=None, occurred_at="2026-09-06T10:00:00Z", sequence=None):
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.stage_completed",
        project_id=project_id,
        occurred_at=occurred_at,
        task_id=task_id,
        payload={},
        sequence=sequence,
    )


def test_append_assigns_monotonic_per_project_sequence():
    log = WorkflowEventLog()

    log.append(event("E-1"))
    log.append(event("E-2"))
    log.append(event("E-3"))

    assert [item.sequence for item in log.list_for_project("PROJECT-001")] == [1, 2, 3]


def test_sequences_are_isolated_per_project():
    log = WorkflowEventLog()

    log.append(event("E-1", project_id="P-1"))
    log.append(event("E-2", project_id="P-2"))
    log.append(event("E-3", project_id="P-1"))

    assert [item.sequence for item in log.list_for_project("P-1")] == [1, 2]
    assert [item.sequence for item in log.list_for_project("P-2")] == [1]


def test_sequence_survives_serialization_round_trip():
    log = WorkflowEventLog()
    log.append(event("E-1"))

    restored = WorkflowEvent.from_dict(log.get("E-1").to_dict())

    assert restored.sequence == 1
    # Sequence is log-position metadata: equality compares event facts only.
    assert restored == event("E-1")


def test_legacy_unsequenced_events_remain_valid_and_deduplicate():
    log = WorkflowEventLog()
    legacy = event("E-1")
    assert legacy.sequence is None

    assert log.append_if_absent(legacy) is True
    assert log.append_if_absent(event("E-1")) is False
    assert log.get("E-1").sequence == 1


def test_list_for_project_orders_by_sequence_not_timestamp():
    log = WorkflowEventLog()

    log.append(event("E-1", occurred_at="2026-09-06T10:00:02Z"))
    log.append(event("E-2", occurred_at="2026-09-06T10:00:01Z"))

    assert [item.event_id for item in log.list_for_project("PROJECT-001")] == ["E-1", "E-2"]


def test_list_for_task_orders_by_sequence():
    log = WorkflowEventLog()

    log.append(event("E-1", task_id="TASK-1", occurred_at="2026-09-06T10:00:05Z"))
    log.append(event("E-2", task_id="TASK-1", occurred_at="2026-09-06T10:00:01Z"))

    assert [item.event_id for item in log.list_for_task("TASK-1")] == ["E-1", "E-2"]


def test_merge_honors_persisted_sequences_and_advances_the_counter():
    log = WorkflowEventLog()
    recovered = event("E-5", sequence=5)
    legacy = event("E-legacy")

    log.merge([recovered, legacy])

    assert log.get("E-5").sequence == 5
    # Legacy events recovered without a sequence keep the timestamp ordering
    # contract; they never receive retroactive sequence numbers.
    assert log.get("E-legacy").sequence is None

    # A subsequent live append continues from the recovered counter.
    log.append(event("E-6"))
    assert log.get("E-6").sequence == 6


def test_concurrent_appends_receive_unique_dense_sequences():
    log = WorkflowEventLog()
    count = 50
    barrier = threading.Barrier(count)

    def append(index: int) -> None:
        barrier.wait()
        log.append(event(f"E-{index:03d}"))

    threads = [threading.Thread(target=append, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    sequences = sorted(item.sequence for item in log.list_for_project("PROJECT-001"))
    assert sequences == list(range(1, count + 1))
