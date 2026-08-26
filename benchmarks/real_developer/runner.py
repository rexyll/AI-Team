from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Protocol

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus

from .metrics import RealDeveloperBenchmarkResult, RealDeveloperTaskMetrics


class DeveloperExecutor(Protocol):
    def run_task(self, task: Task, developer_id: str) -> RealDeveloperTaskMetrics: ...


@dataclass(frozen=True)
class RealDeveloperScenario:
    name: str
    tasks: tuple[Task, ...]


class RealDeveloperBenchmark:
    """Run a controlled Developer benchmark with instrumentation hooks.

    The benchmark measures Developer execution, not Reviewer approval. A
    successful Developer therefore leaves its task in ``review_pending``;
    benchmark DAG readiness explicitly treats that state as satisfied for
    downstream Developer work without changing the normal TaskManager policy.
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
        executor = self.executor_factory(manager, developer_count)
        task_metrics: list[RealDeveloperTaskMetrics] = []
        started = perf_counter()

        with ThreadPoolExecutor(max_workers=developer_count) as pool:
            while True:
                ready = manager.get_ready_tasks(
                    dependency_satisfied_statuses={
                        TaskStatus.COMPLETED.value,
                        TaskStatus.REVIEW_PENDING.value,
                    }
                )
                if not ready:
                    break

                futures = [
                    pool.submit(
                        executor.run_task,
                        task,
                        f"developer-{index % developer_count + 1}",
                    )
                    for index, task in enumerate(ready)
                ]
                for future in futures:
                    task_metrics.append(future.result())

        duration = perf_counter() - started
        final_tasks = manager.get_all_tasks()
        completed_statuses = {
            TaskStatus.COMPLETED.value,
            TaskStatus.REVIEW_PENDING.value,
        }
        completed = sum(1 for task in final_tasks if task.status in completed_statuses)
        failed = sum(1 for task in final_tasks if task.status == TaskStatus.FAILED.value)
        blocked = sum(1 for task in final_tasks if task.status == TaskStatus.BLOCKED.value)

        return RealDeveloperBenchmarkResult.from_task_metrics(
            scenario=self.scenario_name,
            developer_count=developer_count,
            task_count=len(final_tasks),
            completed=completed,
            failed=failed,
            blocked=blocked,
            duration_seconds=duration,
            task_metrics=tuple(task_metrics),
        )
