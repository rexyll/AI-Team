from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_projection import WorkflowEventProjector
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-CONCURRENCY-001"
TASK_IDS = tuple(f"TASK-{index:03d}" for index in range(8))


def _event(index: int, task_id: str) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=f"EVENT-{index:04d}",
        event_type="task_started",
        project_id=PROJECT_ID,
        occurred_at=f"2026-08-22T12:{index // 60:02d}:{index % 60:02d}Z",
        task_id=task_id,
        payload={"status": "running", "index": index},
    )


def test_concurrent_append_and_global_queries_preserve_identity():
    log = WorkflowEventLog()
    events = [_event(index, TASK_IDS[index % len(TASK_IDS)]) for index in range(256)]

    def append(event: WorkflowEvent) -> None:
        log.append(event)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(append, events))

    listed = log.list_all()
    assert len(listed) == len(events)
    assert {event.event_id for event in listed} == {event.event_id for event in events}
    assert len({event.event_id for event in listed}) == len(events)


def test_concurrent_project_and_task_queries_never_mutate_event_log():
    log = WorkflowEventLog()
    events = [_event(index, TASK_IDS[index % len(TASK_IDS)]) for index in range(192)]
    for event in events:
        log.append(event)

    before = {event.event_id for event in log.list_all()}

    def query(index: int) -> tuple[int, int, int]:
        project = log.list_for_project(PROJECT_ID)
        task = log.list_for_task(TASK_IDS[index % len(TASK_IDS)])
        all_events = log.list_all()
        return len(project), len(task), len(all_events)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(query, range(128)))

    assert all(project_count == len(events) for project_count, _, _ in results)
    assert all(task_count > 0 for _, task_count, _ in results)
    assert all(all_count == len(events) for _, _, all_count in results)
    assert {event.event_id for event in log.list_all()} == before


def test_projection_and_query_service_are_safe_during_concurrent_appends():
    log = WorkflowEventLog()
    events = [_event(index, TASK_IDS[index % len(TASK_IDS)]) for index in range(160)]

    def append(event: WorkflowEvent) -> None:
        log.append(event)

    def read_projection(index: int) -> tuple[int, str, int]:
        projection = WorkflowEventProjector.project(log, project_id=PROJECT_ID)
        service = WorkflowEventQueryService.from_log(log, project_id=PROJECT_ID)
        return len(projection.tasks), service.lifecycle(), len(service.as_dict()["tasks"])

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = []
        for index, event in enumerate(events):
            futures.append(executor.submit(append, event))
            if index % 4 == 0:
                futures.append(executor.submit(read_projection, index))
        results = [future.result() for future in futures]

    reads = [result for result in results if isinstance(result, tuple)]
    assert reads
    assert all(task_count <= len(TASK_IDS) for task_count, _, dict_count in reads)
    assert all(task_count == dict_count for task_count, _, dict_count in reads)
    assert len(log) == len(events)
    final = WorkflowEventProjector.project(log, project_id=PROJECT_ID)
    assert len(final.tasks) == len(TASK_IDS)


def test_concurrent_queries_over_persisted_backing_store_are_read_only(tmp_path: Path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    events = [_event(index, TASK_IDS[index % len(TASK_IDS)]) for index in range(128)]
    adapter.save_if_absent_many(events)
    before = sorted(path.name for path in tmp_path.iterdir())

    def query(index: int) -> tuple[int, int, str]:
        log = adapter.load_log()
        projection = WorkflowEventProjector.project(log, project_id=PROJECT_ID)
        service = WorkflowEventQueryService.from_persistence(adapter, project_id=PROJECT_ID)
        return len(log), len(projection.tasks), service.lifecycle()

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(query, range(128)))

    assert all(event_count == len(events) for event_count, _, _ in results)
    assert all(task_count == len(TASK_IDS) for _, task_count, _ in results)
    assert all(lifecycle == "running" for _, _, lifecycle in results)
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_concurrent_append_with_durable_sink_preserves_memory_persistence_identity(tmp_path: Path):
    adapter = WorkflowEventPersistenceAdapter(tmp_path)
    log = WorkflowEventLog(persistence_sink=adapter)
    events = [_event(index, TASK_IDS[index % len(TASK_IDS)]) for index in range(128)]

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(log.append, events))

    persisted = adapter.list_all()
    memory = log.list_all()
    assert [event.event_id for event in memory] == [event.event_id for event in persisted]
    assert {event.event_id for event in persisted} == {event.event_id for event in events}
    assert len(persisted) == len(events)


def test_concurrent_readers_do_not_observe_partial_projection_snapshots():
    log = WorkflowEventLog()
    for index in range(64):
        log.append(_event(index, TASK_IDS[index % len(TASK_IDS)]))

    def read() -> dict:
        return WorkflowEventQueryService.from_log(log, project_id=PROJECT_ID).as_dict()

    with ThreadPoolExecutor(max_workers=16) as executor:
        snapshots = list(executor.map(lambda _: read(), range(128)))

    assert all(snapshot == snapshots[0] for snapshot in snapshots)
    assert snapshots[0]["project_id"] == PROJECT_ID
    assert len(snapshots[0]["tasks"]) == len(TASK_IDS)
