from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.workflow_factory import create_task_workflow
from runtime.context_builder import build_task_context
from runtime.dependency_scheduler import DependencyScheduler
from runtime.retry_policy import FailureKind, decide_retry
from runtime.task_executor import TaskLayerExecutor
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


class _OrchestratorWorkflowEventLog(WorkflowEventLog):
    """Delegate workflow events while reserving task failure for Orchestrator.

    TaskWorkflow owns stage-level success events, while Orchestrator owns the
    task-level failure/retry lifecycle. Developer exceptions are re-raised by
    TaskWorkflow, so forwarding ``developer_failed`` would duplicate the
    authoritative ``task_failed`` event emitted here.
    """

    def __init__(self, delegate: WorkflowEventLog) -> None:
        super().__init__()
        self._delegate = delegate

    def append(self, event: WorkflowEvent) -> None:
        if event.event_type == "developer_failed":
            return
        self._delegate.append(event)

    def append_if_absent(self, event: WorkflowEvent) -> bool:
        if event.event_type == "developer_failed":
            return False
        return self._delegate.append_if_absent(event)


class Orchestrator:
    """Schedule tasks and delegate per-task execution to the proper workflow."""

    def __init__(
        self,
        task_manager: TaskManager,
        agent_router: AgentRouter,
        max_workers: int = 4,
        failure_classifier: Callable[[BaseException], FailureKind] | None = None,
        workflow_event_log: WorkflowEventLog | None = None,
        project_id: str | None = None,
    ):
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.task_executor = TaskLayerExecutor(max_workers=max_workers)
        self.failure_classifier = failure_classifier or self._default_failure_classifier
        self._state_change_hook: Callable[[TaskManager], None] | None = None
        self._workflow_event_log = workflow_event_log
        self._workflow_event_sink = (
            _OrchestratorWorkflowEventLog(workflow_event_log)
            if workflow_event_log is not None
            else None
        )
        self._project_id = project_id

    def set_state_change_hook(self, hook: Callable[[TaskManager], None] | None) -> None:
        """Install an optional callback for durable task-state checkpoints."""
        if hook is not None and not callable(hook):
            raise TypeError("hook must be callable or None")
        self._state_change_hook = hook

    def _persist_state_checkpoint(self, task_manager: TaskManager | None = None) -> None:
        """Emit a checkpoint using the workflow hook contract."""
        hook = self._state_change_hook
        if hook is not None:
            hook(task_manager if task_manager is not None else self.task_manager)

    def _emit_event(self, event_type: str, task, *, payload: dict[str, Any] | None = None) -> None:
        if self._workflow_event_log is None:
            return
        project_id = self._project_id or task.context.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id is required when workflow_event_log is enabled")
        self._workflow_event_log.append(
            WorkflowEvent(
                event_id=str(uuid4()),
                event_type=event_type,
                project_id=project_id,
                task_id=task.id,
                occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                payload=payload or {},
            )
        )

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
            self.task_executor.run_layer(ready_tasks, self._execute_task)

        print("\n" + "=" * 60)
        print("AI TEAM FINISHED" if self.task_manager.is_finished() else "AI TEAM STOPPED")
        print("=" * 60)

    def _get_executable_tasks(self):
        """Use DependencyScheduler as the dependency decision source."""
        scheduler = DependencyScheduler(self.task_manager.get_all_tasks())

        while True:
            blocked_decisions = scheduler.get_blocked_decisions()
            if not blocked_decisions:
                break
            for decision in blocked_decisions:
                self.task_manager.mark_blocked(
                    decision.task_id,
                    decision.reason or "Blocked by dependencies",
                )
            scheduler = DependencyScheduler(self.task_manager.get_all_tasks())

        scheduled_tasks = scheduler.get_ready_tasks()
        for task in scheduled_tasks:
            if task.status == "pending":
                self.task_manager.mark_ready(task.id)

        already_ready = [task for task in self.task_manager.get_all_tasks() if task.status == "ready"]
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

            if task.status == "ready":
                self.task_manager.mark_running(task.id)
                self._emit_event("task_started", task, payload={"status": task.status})
                self._persist_state_checkpoint()

            if task.role == "developer":
                workflow = create_task_workflow(
                    task_manager=self.task_manager,
                    agent_router=self.agent_router,
                    state_change_hook=self._persist_state_checkpoint,
                    workflow_event_log=self._workflow_event_sink,
                    project_id=self._project_id,
                )
                workflow.execute(task.id)
            else:
                agent = self.agent_router.get_agent(task.role)
                result = agent.run(task)
                self.task_manager.mark_completed(task.id, result)
                self._emit_event("task_completed", task, payload={"status": task.status})

            if task.role != "developer":
                self._persist_state_checkpoint()
            print(f"[Completed] {task.id} ({task.status})")

        except Exception as exc:
            # TaskWorkflow owns stage transitions and therefore may already
            # have moved the task to ``failed`` before re-raising an exception.
            # The Orchestrator still owns the task-level failure lifecycle, so
            # emit ``task_failed`` for both the pre-transition and post-
            # transition failure states, before applying retry policy.
            if task.status in {"running", "reviewing", "review_pending", "failed"}:
                if task.status != "failed":
                    self.task_manager.mark_failed(task.id, f"{type(exc).__name__}: {exc}")
                self._emit_event("task_failed", task, payload={"status": task.status, "error": task.error})

            self._apply_retry_policy(task, exc)
            self._persist_state_checkpoint()
            print(f"[Failed] {task.id}: {exc}")

    def _apply_retry_policy(self, task, error: BaseException) -> bool:
        """Apply retry policy after failure, at the Orchestrator boundary."""
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

        self.task_manager.retry_task(task.id, reason=decision.reason, retryable=True)
        self._emit_event(
            "task_retrying",
            task,
            payload={
                "status": task.status,
                "retry_attempt": task.retry_attempt,
                "max_retries": task.max_retries,
                "reason": decision.reason,
            },
        )
        return True

    def _handle_no_ready_tasks(self) -> None:
        print("\n[ERROR] 没有可以执行的任务。\n")
        print("当前任务状态：")
        for task in self.task_manager.get_all_tasks():
            error = f" | {task.error}" if task.error else ""
            print(f"{task.id:<10}{task.status:<14}{task.role:<12}{task.title}{error}")
