from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Protocol

from runtime.task import Task
from runtime.task_manager import TaskManager

from .metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


class DeveloperExecutor(Protocol):
    def run_task(self, task: Task, developer_id: str) -> RealDeveloperTaskMetrics: ...


@dataclass(frozen=True)
class RealDeveloperScenario:
    name: str
    tasks: tuple[Task, ...]


class RealDeveloperBenchmark:
    """Run a controlled Developer benchmark with instrumentation hooks.

    This layer deliberately does not call a model provider itself. The injected
    executor can wrap the existing DeveloperAgent and report LLM/token metrics.
    Provider access stays outside the benchmark so credentials and network
    behavior do not become benchmark logic.
    """

    def __init__(
        self,
        *,
        scenario_factory: Callable[[], list[Task]],
        executor_factory: Callable[[TaskManager, int], DeveloperExecutor],
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

    def run(self, developer_count: int) -> RealDeveloperBenchmarkResult:
        if not isinstance(developer_count, int) or isinstance(developer_count, bool):
            raise TypeError("developer_count must be an integer")
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")

        tasks = self.scenario_factory()
        manager = TaskManager(tasks)
        for task in manager.get_all_tasks():
            if task.status == "pending" and not task.dependencies:
                manager.mark_ready(task.id)

        executor = self.executor_factory(manager, developer_count)
        task_metrics: list[RealDeveloperTaskMetrics] = []
        started = perf_counter()

        # Advance one dependency-ready round at a time. The injected executor
        # owns the actual task execution policy; this runner only supplies work
        # and collects instrumentation. Re-evaluating readiness after each task
        # ensures convergence tasks are included after their prerequisites finish.
        while True:
            ready = [
                task
                for task in manager.get_all_tasks()
                if task.status == "ready"
                and all(
                    manager.get_task(dep).status == "completed"
                    for dep in task.dependencies
                )
            ]
            if not ready:
                break

            for task in ready:
                developer_id = f"developer-{len(task_metrics) % developer_count + 1}"
                metrics = executor.run_task(task, developer_id)
                task_metrics.append(metrics)

        duration = perf_counter() - started
        final_tasks = manager.get_all_tasks()
        counts = {status: 0 for status in ("completed", "failed", "blocked")}
        for task in final_tasks:
            if task.status in counts:
                counts[task.status] += 1

        return RealDeveloperBenchmarkResult.from_task_metrics(
            scenario=self.scenario_name,
            developer_count=developer_count,
            task_count=len(final_tasks),
            completed=counts["completed"],
            failed=counts["failed"],
            blocked=counts["blocked"],
            duration_seconds=duration,
            task_metrics=tuple(task_metrics),
        )
