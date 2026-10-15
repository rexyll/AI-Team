from __future__ import annotations

from time import perf_counter

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT_ID = "PROJECT-PERFORMANCE-REGRESSION-001"
SIZES = (32, 128, 512)


def _events(size: int) -> list[WorkflowEvent]:
    return [
        WorkflowEvent(
            event_id=f"EVENT-REG-{index:04d}",
            event_type="task_started",
            project_id=PROJECT_ID,
            task_id=f"TASK-REG-{index:04d}",
            occurred_at=f"2026-08-22T12:00:{index % 60:02d}Z",
            payload={"status": "running"},
        )
        for index in range(size)
    ]


def _persistence_throughput(tmp_path, size: int) -> float:
    adapter = WorkflowEventPersistenceAdapter(tmp_path / str(size))
    events = _events(size)
    started = perf_counter()
    created = adapter.save_if_absent_many(events)
    elapsed = perf_counter() - started
    assert created == size
    assert len(adapter.list_ids()) == size
    return size / elapsed if elapsed else float("inf")


def test_event_persistence_throughput_does_not_collapse_with_scale(tmp_path) -> None:
    throughputs = {
        size: _persistence_throughput(tmp_path, size)
        for size in SIZES
    }

    # This is deliberately a broad regression guard rather than a machine-
    # specific SLA. A larger batch may be slower per event because each event
    # is durably published, but scaling must not collapse catastrophically.
    assert throughputs[128] > throughputs[32] * 0.30
    assert throughputs[512] > throughputs[32] * 0.20


def _query_throughput(size: int) -> float:
    log = WorkflowEventLog()
    log.merge(_events(size))

    # Use the same number of steady-state samples for every dataset size.
    # Scaling the repetition count inversely with ``size`` made the largest
    # case run only a handful of timed iterations, making it disproportionately
    # sensitive to Windows scheduler/GC/timer noise. A fixed sample count keeps
    # the comparison statistically comparable while retaining enough total work
    # to expose an accidental quadratic projection regression.
    repetitions = 32
    started = perf_counter()
    for _ in range(repetitions):
        query = WorkflowEventQueryService.from_log(log, project_id=PROJECT_ID)
        assert query.lifecycle() == "running"
        assert len(query.as_dict()["tasks"]) == size
    elapsed = perf_counter() - started
    return (size * repetitions) / elapsed if elapsed else float("inf")


def test_projection_query_throughput_does_not_collapse_with_scale() -> None:
    throughputs = {size: _query_throughput(size) for size in SIZES}

    # Projection is intentionally rebuilt from a stable read-only snapshot.
    # Keep the guard wide enough for normal CI variance while detecting an
    # accidental quadratic regression in event/task projection. The benchmark
    # uses equal repeated steady-state samples to avoid a one-shot timer artifact
    # and to keep the largest dataset from being represented by only a few calls.
    assert throughputs[128] > throughputs[32] * 0.30
    assert throughputs[512] > throughputs[32] * 0.20


def test_regression_guard_keeps_canonical_workflow_event_budget() -> None:
    class _Developer:
        role = "developer"

        def run(self, task: Task) -> dict:
            return {
                "status": "completed",
                "agent": "developer",
                "task_id": task.id,
                "message": "canonical workflow event budget regression guard",
            }

    class _Reviewer:
        role = "reviewer"

        def run(self, task: Task) -> dict:
            return {
                "status": "approved",
                "agent": "reviewer",
                "task_id": task.id,
                "message": "canonical workflow event budget regression guard approved",
            }

    router = AgentRouter()
    router.register("developer", _Developer())
    router.register("reviewer", _Reviewer())
    size = 128
    manager = TaskManager(
        [
            Task(
                id=f"TASK-BUDGET-{index:04d}",
                title=f"budget task {index}",
                description="canonical workflow event budget regression guard",
                role="developer",
            )
            for index in range(size)
        ]
    )
    log = WorkflowEventLog()

    Orchestrator(
        manager,
        router,
        max_workers=4,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    ).run()

    assert len(log) == size * 5
    assert all(task.status == "completed" for task in manager.get_all_tasks())
