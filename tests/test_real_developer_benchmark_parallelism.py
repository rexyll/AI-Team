from __future__ import annotations

from threading import Lock
from time import sleep

from benchmarks.real_developer.metrics import RealDeveloperTaskMetrics
from benchmarks.real_developer.runner import RealDeveloperBenchmark
from runtime.task import Task


class _ParallelExecutor:
    def __init__(self, manager, developer_count):
        self.manager = manager
        self.developer_count = developer_count
        self._lock = Lock()
        self.active = 0
        self.max_active = 0

    def run_task(self, task, developer_id):
        self.manager.mark_running(task.id)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            sleep(0.03)
            self.manager.mark_developer_completed(task.id, {"benchmark": "parallel"})
        finally:
            with self._lock:
                self.active -= 1
        return RealDeveloperTaskMetrics(
            task_id=task.id,
            developer_id=developer_id,
            duration_seconds=0.03,
            llm_calls=1,
        )


def _factory():
    return [
        Task("ROOT", "Root", "root", "developer", status="completed"),
        Task("A", "A", "A", "developer", dependencies=["ROOT"]),
        Task("B", "B", "B", "developer", dependencies=["ROOT"]),
        Task("C", "C", "C", "developer", dependencies=["ROOT"]),
        Task("FINAL", "Final", "final", "developer", dependencies=["A", "B", "C"]),
    ]


def test_real_developer_benchmark_executes_ready_batch_concurrently():
    observed = {}

    def executor_factory(manager, developer_count):
        executor = _ParallelExecutor(manager, developer_count)
        observed["executor"] = executor
        return executor

    benchmark = RealDeveloperBenchmark(
        scenario_factory=_factory,
        executor_factory=executor_factory,
        scenario_name="parallel-contract",
    )

    result = benchmark.run(3)

    assert result.completed == 5
    assert result.failed == 0
    assert result.blocked == 0
    assert len(result.task_metrics) == 4
    assert observed["executor"].max_active == 3
