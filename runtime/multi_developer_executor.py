from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from typing import Callable

from runtime.agent_router import AgentRouter
from runtime.dependency_scheduler import DependencyScheduler
from runtime.task import Task
from runtime.task_manager import TaskManager


@dataclass(frozen=True)
class DeveloperAssignment:
    """Immutable record of one task-to-developer scheduling decision."""

    task_id: str
    developer_id: str


class MultiDeveloperExecutor:
    """Execute dependency-ready tasks concurrently across Developer agents.

    Scheduling decisions are dependency-aware and task lifecycle ownership
    remains in TaskManager. A task is claimed by the atomic READY -> RUNNING
    transition before its workflow is submitted, so duplicate claims from
    concurrent scheduling passes are rejected by the existing state machine.
    Reviewer/Tester execution remains inside each TaskWorkflow; this class
    only owns project-level Developer concurrency.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        agent_router: AgentRouter,
        workflow_factory: Callable[[object], object],
        *,
        max_workers: int | None = None,
    ) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if not isinstance(agent_router, AgentRouter):
            raise TypeError("agent_router must be an AgentRouter")
        if not callable(workflow_factory):
            raise TypeError("workflow_factory must be callable")
        if max_workers is not None:
            if not isinstance(max_workers, int) or isinstance(max_workers, bool):
                raise TypeError("max_workers must be an integer or None")
            if max_workers <= 0:
                raise ValueError("max_workers must be greater than 0")

        developers = agent_router.get_developers()
        if not developers:
            raise ValueError("at least one Developer agent is required")
        if max_workers is not None and max_workers > len(developers):
            raise ValueError("max_workers cannot exceed the number of Developer agents")

        self.task_manager = task_manager
        self.agent_router = agent_router
        self.workflow_factory = workflow_factory
        self.max_workers = max_workers or len(developers)
        self._assignment_lock = Lock()
        self._assignments: dict[str, DeveloperAssignment] = {}

    @property
    def assignments(self) -> tuple[DeveloperAssignment, ...]:
        with self._assignment_lock:
            return tuple(self._assignments.values())

    def run_until_idle(self) -> list[Task]:
        """Run all currently executable work until no further progress exists."""
        completed: dict[str, Task] = {}

        while True:
            self.task_manager.get_ready_tasks()
            ready = DependencyScheduler(self.task_manager.get_all_tasks()).get_ready_tasks()
            candidates = [task for task in ready if task.id not in self._assigned_task_ids()]
            if not candidates:
                break

            futures: dict[Future, DeveloperAssignment] = {}
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                for task in candidates:
                    developer = self.agent_router.get_developer_for_task(task.id)
                    developer_id = self._developer_id(developer)
                    try:
                        # READY -> RUNNING is the atomic claim operation.
                        self.task_manager.mark_running(task.id)
                    except ValueError:
                        continue

                    assignment = DeveloperAssignment(task.id, developer_id)
                    with self._assignment_lock:
                        self._assignments[task.id] = assignment
                    workflow = self.workflow_factory(developer)
                    futures[executor.submit(self._execute_claimed, workflow, task.id)] = assignment

                for future in as_completed(futures):
                    assignment = futures[future]
                    try:
                        task = future.result()
                    finally:
                        with self._assignment_lock:
                            self._assignments.pop(assignment.task_id, None)
                    completed[task.id] = task

        return [completed[task.id] for task in self.task_manager.get_all_tasks() if task.id in completed]

    def _execute_claimed(self, workflow: object, task_id: str) -> Task:
        execute = getattr(workflow, "execute", None)
        if not callable(execute):
            raise TypeError("workflow_factory must return an object with execute(task_id)")
        return execute(task_id)

    def _assigned_task_ids(self) -> set[str]:
        with self._assignment_lock:
            return set(self._assignments)

    @staticmethod
    def _developer_id(developer: object) -> str:
        config = getattr(developer, "config", None)
        extra = getattr(config, "extra", None)
        if isinstance(extra, dict):
            value = extra.get("developer_id")
            if isinstance(value, str) and value.strip():
                return value
        value = getattr(developer, "developer_id", None)
        if isinstance(value, str) and value.strip():
            return value
        return f"developer-{id(developer)}"
