from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep

import pytest

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog


PROJECT_ID = "PROJECT-PERFORMANCE-001"
# The baseline router intentionally registers only Developer + Reviewer, so
# the canonical workflow skips Tester. A first-pass approval therefore emits
# five lifecycle events per task:
# task_started, developer_completed, tester_skipped, review_started,
# reviewer_approved.
EVENTS_PER_TASK = 5
EXPECTED_EVENT_TYPES = [
    "task_started",
    "developer_completed",
    "tester_skipped",
    "review_started",
    "reviewer_approved",
]


@dataclass
class _PerformanceMetrics:
    task_count: int
    max_workers: int
    elapsed_seconds: float
    tasks_per_second: float
    events_per_second: float


class _BaselineDeveloper:
    role = "developer"

    def run(self, task: Task) -> dict:
        # A small deterministic delay makes parallelism observable without
        # depending on a network, filesystem, or real LLM provider.
        sleep(0.001)
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "performance baseline",
        }


class _BaselineReviewer:
    role = "reviewer"

    def run(self, task: Task) -> dict:
        sleep(0.001)
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "performance baseline approved",
        }


def _manager(task_count: int) -> TaskManager:
    return TaskManager(
        [
            Task(
                id=f"TASK-PERF-{index:04d}",
                title=f"performance task {index}",
                description="deterministic workflow performance baseline",
                role="developer",
            )
            for index in range(1, task_count + 1)
        ]
    )


def _router() -> AgentRouter:
    router = AgentRouter()
    router.register("developer", _BaselineDeveloper())
    router.register("reviewer", _BaselineReviewer())
    return router


def _run_baseline(task_count: int, max_workers: int) -> _PerformanceMetrics:
    manager = _manager(task_count)
    log = WorkflowEventLog()
    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=_router(),
        max_workers=max_workers,
        workflow_event_log=log,
        project_id=PROJECT_ID,
    )

    started = perf_counter()
    orchestrator.run()
    elapsed = perf_counter() - started

    tasks = manager.get_all_tasks()
    assert len(tasks) == task_count
    assert all(task.status == "completed" for task in tasks)
    assert len(log) == task_count * EVENTS_PER_TASK
    assert len({event.event_id for event in log.list_all()}) == len(log)
    for task in tasks:
        assert [event.event_type for event in log.list_for_task(task.id)] == EXPECTED_EVENT_TYPES

    return _PerformanceMetrics(
        task_count=task_count,
        max_workers=max_workers,
        elapsed_seconds=elapsed,
        tasks_per_second=task_count / elapsed if elapsed else float("inf"),
        events_per_second=len(log) / elapsed if elapsed else float("inf"),
    )


@pytest.mark.parametrize("task_count", [32, 128, 512])
def test_workflow_performance_baseline_scales_without_semantic_loss(task_count: int, capsys) -> None:
    metrics = _run_baseline(task_count, max_workers=1)
    capsys.readouterr()

    assert metrics.elapsed_seconds > 0
    assert metrics.tasks_per_second > 0
    assert metrics.events_per_second > 0
    assert metrics.events_per_second == pytest.approx(
        metrics.tasks_per_second * EVENTS_PER_TASK,
        rel=1e-9,
    )


@pytest.mark.parametrize("task_count", [32, 128, 512])
def test_workflow_parallel_baseline_is_bounded_and_productive(task_count: int, capsys) -> None:
    single = _run_baseline(task_count, max_workers=1)
    capsys.readouterr()
    parallel = _run_baseline(task_count, max_workers=4)
    capsys.readouterr()

    assert parallel.max_workers == 4
    assert parallel.elapsed_seconds > 0
    assert parallel.tasks_per_second > 0
    assert parallel.events_per_second > 0

    # Do not require linear scaling: this is intentionally a soft contract
    # against pathological scheduler behavior, not a machine-specific SLA.
    assert parallel.tasks_per_second > single.tasks_per_second * 1.05
