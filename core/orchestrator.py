from collections.abc import Callable

from core.workflow_factory import create_task_workflow
from runtime.context_builder import build_task_context
from runtime.dependency_scheduler import DependencyScheduler
from runtime.retry_policy import FailureKind, decide_retry
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
        failure_classifier: Callable[[BaseException], FailureKind] | None = None,
    ):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.task_executor = TaskLayerExecutor(max_workers=max_workers)
        self.failure_classifier = (
            failure_classifier or self._default_failure_classifier
        )
        self._state_change_hook: Callable[[TaskManager], None] | None = None

    def set_state_change_hook(
        self,
        hook: Callable[[TaskManager], None] | None,
    ) -> None:
        """Install an optional callback for durable task-state checkpoints."""
        if hook is not None and not callable(hook):
            raise TypeError("hook must be callable or None")
        self._state_change_hook = hook

    def _persist_state_checkpoint(
        self,
        task_manager: TaskManager | None = None,
    ) -> None:
        """Emit a checkpoint using the workflow hook contract.

        TaskWorkflow invokes stage checkpoints with its TaskManager argument,
        while Orchestrator also emits checkpoints internally without an
        argument. Accept both forms so the same bound method can safely cross
        the Orchestrator -> Workflow boundary.
        """
        hook = self._state_change_hook
        if hook is not None:
            hook(task_manager if task_manager is not None else self.task_manager)

    @staticmethod
    def _default_failure_classifier(error: BaseException) -> FailureKind:
        """Classify execution failures without involving Agent/Workflow code."""
        if isinstance(error, (TypeError, ValueError, KeyError)):
            return FailureKind.NON_RETRYABLE
        return FailureKind.EXECUTION

    def run(self) -> None:
        print("\n" + "=" * 60)
        print("AI TEAM START")
        print("=" * 60)

        while not self.task_manager.is_finished():
            ready_tasks = self._get_executable_tasks()

            if not ready_tasks:
                self._handle_no_ready_tasks()
                break

            self._persist_state_checkpoint()
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

        for task in scheduled_tasks:
            if task.status == "pending":
                self.task_manager.mark_ready(task.id)

        already_ready = [
            task
            for task in self.task_manager.get_all_tasks()
            if task.status == "ready"
        ]

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

            # The orchestrator owns the task execution boundary. Mark the
            # task running before entering either the single-agent path or
            # the Developer -> Tester -> Reviewer workflow so a persisted
            # checkpoint never claims executable work is still merely ready.
            if task.status == "ready":
                self.task_manager.mark_running(task.id)
                self._persist_state_checkpoint()

            if task.role == "developer":
                workflow = create_task_workflow(
                    task_manager=self.task_manager,
                    agent_router=self.agent_router,
                    state_change_hook=self._persist_state_checkpoint,
                )
                workflow.execute(task.id)
            else:
                agent = self.agent_router.get_agent(task.role)
                result = agent.run(task)
                self.task_manager.mark_completed(task.id, result)

            self._persist_state_checkpoint()
            print(f"[Completed] {task.id} ({task.status})")

        except Exception as exc:
            if task.status in {"running", "reviewing", "review_pending"}:
                self.task_manager.mark_failed(
                    task.id,
                    f"{type(exc).__name__}: {exc}",
                )

            self._apply_retry_policy(task, exc)
            self._persist_state_checkpoint()
            print(f"[Failed] {task.id}: {exc}")

    def _apply_retry_policy(self, task, error: BaseException) -> bool:
        """Apply retry policy after failure, at the Orchestrator boundary.

        The policy is pure; TaskManager owns all retry/lifecycle mutation.
        A denied decision leaves the failed Task untouched.
        """
        if task.status != "failed":
            return False

        failure_kind = self.failure_classifier(error)
        if not isinstance(failure_kind, FailureKind):
            raise TypeError("failure_classifier must return FailureKind")

        decision = decide_retry(
            attempt=task.retry_attempt,
            max_retries=task.max_retries,
            failure_kind=failure_kind,
            reason=f"{type(error).__name__}: {error}",
        )

        if not decision.retry:
            return False

        self.task_manager.retry_task(
            task.id,
            reason=decision.reason,
            retryable=True,
        )
        return True

    def _handle_no_ready_tasks(self) -> None:
        print("\n[ERROR] 没有可以执行的任务。\n")
        print("当前任务状态：")
        for task in self.task_manager.get_all_tasks():
            error = f" | {task.error}" if task.error else ""
            print(
                f"{task.id:<10}{task.status:<14}"
                f"{task.role:<12}{task.title}{error}"
            )
