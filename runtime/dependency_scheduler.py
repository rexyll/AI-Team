from dataclasses import dataclass

from runtime.dependency_graph import get_execution_layers, topological_sort
from runtime.resource_governor import ResourceGovernor
from runtime.task import Task
from runtime.task_status import TaskStatus


@dataclass(frozen=True)
class SchedulerDecision:
    task_id: str
    runnable: bool
    blocked: bool
    reason: str | None = None


class DependencyScheduler:
    """Compute dependency-aware execution decisions without mutating tasks."""

    def __init__(self, tasks: list[Task]) -> None:
        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")
        if any(not isinstance(task, Task) for task in tasks):
            raise TypeError("all tasks must be Task instances")
        self._tasks = {task.id: task for task in tasks}
        if len(self._tasks) != len(tasks):
            raise ValueError("Duplicate task id")
        self._graph = {task.id: list(task.dependencies) for task in tasks}
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        for task_id, dependencies in self._graph.items():
            for dependency_id in dependencies:
                if dependency_id not in self._tasks:
                    raise ValueError(f"Task {task_id} depends on unknown task {dependency_id}")
        topological_sort(self._graph)

    def get_ready_tasks(self) -> list[Task]:
        return [
            task
            for task in self._tasks.values()
            if task.status in {TaskStatus.PENDING.value, TaskStatus.READY.value}
            and not task.cancellation_requested
            and all(
                self._tasks[d].status == TaskStatus.COMPLETED.value
                for d in task.dependencies
            )
        ]

    def get_admissible_tasks(self, governor: ResourceGovernor) -> list[Task]:
        """Return dependency-ready tasks that fit the current concurrency budget."""
        if not isinstance(governor, ResourceGovernor):
            raise TypeError("governor must be a ResourceGovernor")
        available = governor.limits.max_concurrent_tasks - governor.usage.active_tasks
        if available <= 0:
            return []
        return self.get_ready_tasks()[:available]

    def get_blocked_decisions(self) -> list[SchedulerDecision]:
        decisions: list[SchedulerDecision] = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING.value:
                continue
            failed = [
                d
                for d in task.dependencies
                if self._tasks[d].status
                in {TaskStatus.FAILED.value, TaskStatus.BLOCKED.value}
            ]
            if failed:
                decisions.append(
                    SchedulerDecision(
                        task.id,
                        False,
                        True,
                        "Blocked by dependencies: " + ", ".join(failed),
                    )
                )
        return decisions

    def get_execution_layers(self) -> list[list[str]]:
        return get_execution_layers(self._graph)

    def decision_for(self, task_id: str) -> SchedulerDecision:
        if task_id not in self._tasks:
            raise KeyError(f"Unknown task id: {task_id}")
        task = self._tasks[task_id]
        if task.status == TaskStatus.CANCELLED.value:
            return SchedulerDecision(task_id, False, False, "Task is cancelled")
        if task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.BLOCKED.value,
        }:
            return SchedulerDecision(
                task_id,
                False,
                task.status == TaskStatus.BLOCKED.value,
                f"Task is {task.status}",
            )
        failed = [
            d
            for d in task.dependencies
            if self._tasks[d].status
            in {TaskStatus.FAILED.value, TaskStatus.BLOCKED.value}
        ]
        if failed:
            return SchedulerDecision(
                task_id,
                False,
                True,
                "Blocked by dependencies: " + ", ".join(failed),
            )
        if all(
            self._tasks[d].status == TaskStatus.COMPLETED.value
            for d in task.dependencies
        ):
            return SchedulerDecision(task_id, True, False)
        return SchedulerDecision(
            task_id,
            False,
            False,
            "Dependencies are not completed",
        )