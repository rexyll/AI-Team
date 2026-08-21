from dataclasses import dataclass

from runtime.dependency_graph import build_dependency_graph, get_execution_layers, topological_sort
from runtime.task import Task
from runtime.task_status import TaskStatus


@dataclass(frozen=True)
class SchedulerDecision:
    """Read-only dependency scheduling decision for one task."""

    task_id: str
    runnable: bool
    blocked: bool
    reason: str | None = None


class DependencyScheduler:
    """Compute dependency-aware execution decisions without mutating tasks.

    The scheduler owns *decision making* only. TaskManager remains the sole
    lifecycle mutation boundary. This separation allows the scheduler to be
    used by the future ProjectOrchestrator and parallel executor without
    duplicating task-state mutation logic.
    """

    def __init__(self, tasks: list[Task]) -> None:
        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")
        if any(not isinstance(task, Task) for task in tasks):
            raise TypeError("all tasks must be Task instances")

        self._tasks = {task.id: task for task in tasks}
        if len(self._tasks) != len(tasks):
            raise ValueError("Duplicate task id")

        self._graph = {
            task.id: list(task.dependencies)
            for task in tasks
        }
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        for task_id, dependencies in self._graph.items():
            for dependency_id in dependencies:
                if dependency_id not in self._tasks:
                    raise ValueError(
                        f"Task {task_id} depends on unknown task {dependency_id}"
                    )
        topological_sort(self._graph)

    def get_ready_tasks(self) -> list[Task]:
        """Return pending tasks whose dependencies are all completed.

        Existing ``ready`` tasks are also returned when their dependencies
        remain satisfied. The method never changes task status, error, or
        history.
        """
        return [
            task
            for task in self._tasks.values()
            if task.status in {
                TaskStatus.PENDING.value,
                TaskStatus.READY.value,
            }
            and all(
                self._tasks[dependency_id].status == TaskStatus.COMPLETED.value
                for dependency_id in task.dependencies
            )
        ]

    def get_blocked_decisions(self) -> list[SchedulerDecision]:
        """Return dependency-blocking decisions without mutating tasks."""
        decisions: list[SchedulerDecision] = []

        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING.value:
                continue

            failed = [
                dependency_id
                for dependency_id in task.dependencies
                if self._tasks[dependency_id].status
                in {
                    TaskStatus.FAILED.value,
                    TaskStatus.BLOCKED.value,
                }
            ]

            if failed:
                decisions.append(
                    SchedulerDecision(
                        task_id=task.id,
                        runnable=False,
                        blocked=True,
                        reason="Blocked by dependencies: " + ", ".join(failed),
                    )
                )

        return decisions

    def get_execution_layers(self) -> list[list[str]]:
        """Return deterministic dependency execution layers."""
        return get_execution_layers(self._graph)

    def decision_for(self, task_id: str) -> SchedulerDecision:
        """Return the current dependency decision for one task."""
        if task_id not in self._tasks:
            raise KeyError(f"Unknown task id: {task_id}")

        task = self._tasks[task_id]

        if task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.BLOCKED.value,
        }:
            return SchedulerDecision(
                task_id=task_id,
                runnable=False,
                blocked=task.status == TaskStatus.BLOCKED.value,
                reason=f"Task is {task.status}",
            )

        failed = [
            dependency_id
            for dependency_id in task.dependencies
            if self._tasks[dependency_id].status
            in {
                TaskStatus.FAILED.value,
                TaskStatus.BLOCKED.value,
            }
        ]
        if failed:
            return SchedulerDecision(
                task_id=task_id,
                runnable=False,
                blocked=True,
                reason="Blocked by dependencies: " + ", ".join(failed),
            )

        if all(
            self._tasks[dependency_id].status == TaskStatus.COMPLETED.value
            for dependency_id in task.dependencies
        ):
            return SchedulerDecision(task_id=task_id, runnable=True, blocked=False)

        return SchedulerDecision(
            task_id=task_id,
            runnable=False,
            blocked=False,
            reason="Dependencies are not completed",
        )
