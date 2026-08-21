from collections.abc import Callable

from runtime.dependency_scheduler import DependencyScheduler
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class ProjectOrchestrator:
    """Coordinate dependency scheduling and per-task workflow execution.

    The orchestrator owns project-level sequencing only:

    * DependencyScheduler decides which tasks are runnable.
    * TaskManager remains the only lifecycle mutation boundary.
    * TaskWorkflow executes one task lifecycle.

    This first implementation intentionally does not add parallelism,
    retry/resume, persistence, or project-result aggregation.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        workflow_factory: Callable[[], TaskWorkflow],
    ) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if not callable(workflow_factory):
            raise TypeError("workflow_factory must be callable")

        self.task_manager = task_manager
        self.workflow_factory = workflow_factory

    def _scheduler(self) -> DependencyScheduler:
        """Build a fresh read-only scheduler snapshot from managed tasks."""
        return DependencyScheduler(self.task_manager.get_all_tasks())

    def get_ready_tasks(self) -> list[Task]:
        """Return scheduler decisions without mutating task lifecycle state."""
        return self._scheduler().get_ready_tasks()

    def run(self) -> list[Task]:
        """Execute runnable tasks until no additional task is runnable.

        A fresh scheduler is created after every task execution so dependency
        decisions observe the latest TaskManager state. The orchestrator does
        not assign ``Task.status`` directly.
        """
        executed: list[Task] = []

        while True:
            ready_tasks = self.get_ready_tasks()
            if not ready_tasks:
                break

            task = ready_tasks[0]
            if task.status == "pending":
                self.task_manager.mark_ready(task.id)

            workflow = self.workflow_factory()
            if not isinstance(workflow, TaskWorkflow):
                raise TypeError("workflow_factory must return a TaskWorkflow")

            workflow.execute(task.id)
            executed.append(task)

        return executed
