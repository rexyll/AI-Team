from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from runtime.task import Task
from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class BenchmarkResult:
    """Deterministic summary of one multi-Developer benchmark run."""

    scenario: str
    developer_count: int
    task_count: int
    completed: int
    failed: int
    blocked: int
    duration_seconds: float

    @property
    def speedup(self) -> float | None:
        return None

    @property
    def parallel_efficiency(self) -> float | None:
        return None

    def with_baseline(self, baseline: "BenchmarkResult") -> "BenchmarkResultWithBaseline":
        if baseline.duration_seconds <= 0:
            raise ValueError("baseline duration must be greater than 0")
        if baseline.scenario != self.scenario:
            raise ValueError("baseline scenario must match result scenario")
        return BenchmarkResultWithBaseline(
            result=self,
            speedup=baseline.duration_seconds / self.duration_seconds
            if self.duration_seconds > 0
            else float("inf"),
            parallel_efficiency=(
                baseline.duration_seconds / self.duration_seconds / self.developer_count
                if self.duration_seconds > 0 and self.developer_count > 0
                else 0.0
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "developer_count": self.developer_count,
            "task_count": self.task_count,
            "completed": self.completed,
            "failed": self.failed,
            "blocked": self.blocked,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class BenchmarkResultWithBaseline:
    result: BenchmarkResult
    speedup: float
    parallel_efficiency: float

    def to_dict(self) -> dict[str, object]:
        data = self.result.to_dict()
        data.update({
            "speedup": self.speedup,
            "parallel_efficiency": self.parallel_efficiency,
        })
        return data


class MultiDeveloperBenchmark:
    """Run the same scenario with different Developer counts.

    The runner deliberately does not construct Agents or workflows itself.
    Callers inject an executor factory so benchmark results remain independent
    of model/provider configuration and can use deterministic test doubles.
    """

    def __init__(
        self,
        *,
        scenario_factory: Callable[[], list[Task]],
        executor_factory: Callable[[TaskManager, int], object],
        scenario_name: str,
    ) -> None:
        if not callable(scenario_factory):
            raise TypeError("scenario_factory must be callable")
        if not callable(executor_factory):
            raise TypeError("executor_factory must be callable")
        if not isinstance(scenario_name, str) or not scenario_name.strip():
            raise ValueError("scenario_name must be a non-empty string")
        self.scenario_factory = scenario_factory
        self.executor_factory = executor_factory
        self.scenario_name = scenario_name

    def run(self, developer_count: int) -> BenchmarkResult:
        if not isinstance(developer_count, int) or isinstance(developer_count, bool):
            raise TypeError("developer_count must be an integer")
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")

        tasks = self.scenario_factory()
        manager = TaskManager(tasks)
        # Normalize the scenario's initial lifecycle state before handing the
        # manager to an executor. Production executors may call this themselves,
        # while deterministic benchmark doubles can assume runnable roots are READY.
        manager.get_ready_tasks()
        executor = self.executor_factory(manager, developer_count)

        started = perf_counter()
        executor.run_until_idle()
        duration = perf_counter() - started

        final_tasks = manager.get_all_tasks()
        status_counts = {status: 0 for status in ("completed", "failed", "blocked")}
        for task in final_tasks:
            if task.status in status_counts:
                status_counts[task.status] += 1

        return BenchmarkResult(
            scenario=self.scenario_name,
            developer_count=developer_count,
            task_count=len(final_tasks),
            completed=status_counts["completed"],
            failed=status_counts["failed"],
            blocked=status_counts["blocked"],
            duration_seconds=duration,
        )
