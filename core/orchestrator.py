from core.workflow_factory import create_task_workflow
from runtime.context_builder import build_task_context
from runtime.dependency_scheduler import DependencyScheduler
from runtime.task_executor import TaskLayerExecutor
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter


class Orchestrator:
    """Schedule tasks and delegate per-task execution to the proper workflow."""

    def __init__(
        self,
        task_manager: TaskManager,
        agent_router: AgentRouter,
        max_workers: int = 4,
    ):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.task_executor = TaskLayerExecutor(max_workers=max_workers)

    def run(self) -> None:
        print("\n" + "=" * 60)
        print("AI TEAM START")
        print("=" * 60)

        while not self.task_manager.is_finished():
            ready_tasks = self._get_executable_tasks()

            if not ready_tasks:
                self._handle_no_ready_tasks()
                break

            # One readiness batch is one execution layer. All tasks in the
            # batch may execute concurrently; the next scheduling iteration
            # is the barrier that waits for this layer to finish.
            self.task_executor.run_layer(
                ready_tasks,
                self._execute_task,
            )

        print("\n" + "=" * 60)
        print(
            "AI TEAM FINISHED"
            if self.task_manager.is_finished()
            else "AI TEAM STOPPED"
        )
        print("=" * 60)

    def _get_executable_tasks(self):
        """Use DependencyScheduler as the dependency decision source.

        DependencyScheduler is read-only. TaskManager remains responsible
        for applying ready/blocked lifecycle mutations.
        """
        scheduler = DependencyScheduler(
            self.task_manager.get_all_tasks()
        )

        # Apply scheduler blocked decisions through the sole lifecycle
        # mutation boundary, then rebuild the snapshot so downstream tasks
        # observe newly blocked dependencies.
        while True:
            blocked_decisions = scheduler.get_blocked_decisions()
            if not blocked_decisions:
                break

            for decision in blocked_decisions:
                self.task_manager.mark_blocked(
                    decision.task_id,
                    decision.reason or "Blocked by dependencies",
                )

            scheduler = DependencyScheduler(
                self.task_manager.get_all_tasks()
            )

        scheduled_tasks = scheduler.get_ready_tasks()

        # Scheduler decides readiness; TaskManager applies the state change.
        for task in scheduled_tasks:
            if task.status == "pending":
                self.task_manager.mark_ready(task.id)

        already_ready = [
            task
            for task in self.task_manager.get_all_tasks()
            if task.status == "ready"
        ]

        # Preserve task-manager order while avoiding duplicates.
        executable = []
        seen = set()
        for task in [*scheduled_tasks, *already_ready]:
            if task.id not in seen:
                executable.append(task)
                seen.add(task.id)
        return executable

    def _execute_task(self, task) -> None:
        print("\n" + "-" * 60)
        print(f"{task.id} | {task.role} | {task.title}")
        print("-" * 60)

        try:
            context = build_task_context(task, self.task_manager.tasks)
            task.context = context

            if task.role == "developer":
                workflow = create_task_workflow(
                    task_manager=self.task_manager,
                    agent_router=self.agent_router,
                )
                workflow.execute(task.id)
            else:
                agent = self.agent_router.get_agent(task.role)
                self.task_manager.mark_running(task.id)
                result = agent.run(task)
                self.task_manager.mark_completed(task.id, result)

            print(f"[Completed] {task.id} ({task.status})")

        except Exception as exc:
            if task.status in {"running", "reviewing", "review_pending"}:
                self.task_manager.mark_failed(
                    task.id,
                    f"{type(exc).__name__}: {exc}",
                )
            print(f"[Failed] {task.id}: {exc}")

    def _handle_no_ready_tasks(self) -> None:
        print("\n[ERROR] 没有可以执行的任务。\n")
        print("当前任务状态：")
        for task in self.task_manager.get_all_tasks():
            error = f" | {task.error}" if task.error else ""
            print(
                f"{task.id:<10}{task.status:<14}"
                f"{task.role:<12}{task.title}{error}"
            )
