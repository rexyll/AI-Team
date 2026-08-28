from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.workflow_factory import create_task_workflow
from runtime.context_builder import build_task_context
from runtime.dependency_scheduler import DependencyScheduler
from runtime.failure_classification import FailureClass, classify_failure
from runtime.failure_recovery_executor import FailureRecoveryExecutor, RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction, decide_recovery
from runtime.recovery_replan_coordinator import RecoveryReplanCoordinator
from runtime.retry_policy import FailureKind
from runtime.task_executor import TaskLayerExecutor
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


class _CheckpointFailure(OSError):
    """Signal a durable checkpoint failure without converting task state to failed."""


class _OrchestratorWorkflowEventLog(WorkflowEventLog):
    """Delegate workflow events while reserving task failure for Orchestrator."""

    def __init__(self, delegate: WorkflowEventLog) -> None:
        super().__init__()
        self._delegate = delegate

    def append(self, event: WorkflowEvent) -> None:
        # Assignment is internal routing metadata; the canonical lifecycle
        # contract intentionally remains five events per successful task.
        if event.event_type in {"developer_failed", "developer_assigned"}:
            return
        self._delegate.append(event)

    def append_if_absent(self, event: WorkflowEvent) -> bool:
        if event.event_type in {"developer_failed", "developer_assigned"}:
            return False
        return self._delegate.append_if_absent(event)


class Orchestrator:
    """Schedule tasks and delegate per-task execution to the proper workflow."""

    def __init__(self, task_manager: TaskManager, agent_router: AgentRouter, max_workers: int = 4,
                 failure_classifier: Callable[[BaseException], FailureKind] | None = None,
                 workflow_event_log: WorkflowEventLog | None = None, project_id: str | None = None,
                 replan_planner: Callable[[str], dict[str, Any]] | None = None):
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.task_executor = TaskLayerExecutor(max_workers=max_workers)
        self.failure_classifier = failure_classifier or self._default_failure_classifier
        self.failure_recovery_executor = FailureRecoveryExecutor(task_manager)
        self._replan_coordinator = (
            RecoveryReplanCoordinator(task_manager, replan_planner)
            if replan_planner is not None else None
        )
        self._state_change_hook: Callable[[TaskManager], None] | None = None
        self._workflow_event_log = workflow_event_log
        self._workflow_event_sink = _OrchestratorWorkflowEventLog(workflow_event_log) if workflow_event_log is not None else None
        self._project_id = project_id

    def set_state_change_hook(self, hook: Callable[[TaskManager], None] | None) -> None:
        if hook is not None and not callable(hook):
            raise TypeError("hook must be callable or None")
        self._state_change_hook = hook

    def set_workflow_event_log(self, log: WorkflowEventLog | None, *, project_id: str | None = None) -> None:
        if log is not None and not isinstance(log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        self._workflow_event_log = log
        self._workflow_event_sink = _OrchestratorWorkflowEventLog(log) if log is not None else None
        if project_id is not None:
            self._project_id = project_id

    def _persist_state_checkpoint(self, task_manager: TaskManager | None = None) -> None:
        hook = self._state_change_hook
        if hook is None:
            return
        try:
            hook(task_manager if task_manager is not None else self.task_manager)
        except _CheckpointFailure:
            raise
        except OSError as exc:
            raise _CheckpointFailure(str(exc)) from exc

    def _emit_event(self, event_type: str, task, *, payload: dict[str, Any] | None = None) -> None:
        if self._workflow_event_sink is None:
            return
        project_id = self._project_id or task.context.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id is required when workflow_event_log is enabled")
        self._workflow_event_sink.append(WorkflowEvent(
            event_id=str(uuid4()), event_type=event_type, project_id=project_id,
            task_id=task.id, occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            payload=payload or {},
        ))

    @staticmethod
    def _default_failure_classifier(error: BaseException) -> FailureKind:
        if isinstance(error, (TypeError, ValueError, KeyError)):
            return FailureKind.NON_RETRYABLE
        return FailureKind.EXECUTION

    @staticmethod
    def _failure_class_for_kind(failure_kind: FailureKind) -> FailureClass:
        """Bridge the legacy retry classifier into the new recovery taxonomy."""
        if failure_kind in {
            FailureKind.EXECUTION,
            FailureKind.QUALITY_GATE,
            FailureKind.INVALID_RESULT,
        }:
            return FailureClass.TRANSIENT
        return FailureClass.UNKNOWN

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
        scheduler = DependencyScheduler(self.task_manager.get_all_tasks())
        while True:
            blocked_decisions = scheduler.get_blocked_decisions()
            if not blocked_decisions:
                break
            for decision in blocked_decisions:
                self.task_manager.mark_blocked(decision.task_id, decision.reason or "Blocked by dependencies")
            scheduler = DependencyScheduler(self.task_manager.get_all_tasks())
        scheduled_tasks = scheduler.get_ready_tasks()
        for task in scheduled_tasks:
            if task.status == "pending":
                self.task_manager.mark_ready(task.id)
        already_ready = [task for task in self.task_manager.get_all_tasks() if task.status == "ready"]
        executable, seen = [], set()
        for task in [*scheduled_tasks, *already_ready]:
            if task.id not in seen:
                executable.append(task)
                seen.add(task.id)
        return executable

    def _select_developer(self, task) -> object:
        selector = getattr(self.agent_router, "get_developer_for_task", None)
        if callable(selector):
            return selector(task.id)
        agent = self.agent_router.get_agent("developer")
        if agent is None:
            raise ValueError("No developer agent is registered")
        return agent

    @staticmethod
    def _developer_identity(agent) -> dict[str, Any]:
        config = getattr(agent, "config", None)
        developer_id = None
        model = None
        if config is not None:
            extra = getattr(config, "extra", {})
            if isinstance(extra, dict):
                developer_id = extra.get("developer_id")
            model = getattr(config, "model", None)
        return {"developer_id": developer_id, "model": model}

    def _execute_task(self, task) -> None:
        print("\n" + "-" * 60)
        print(f"{task.id} | {task.role} | {task.title}")
        print("-" * 60)
        try:
            context = build_task_context(task, self.task_manager.tasks)
            task.context["dependencies"] = context
            if task.status == "ready":
                self.task_manager.mark_running(task.id)
                self._emit_event("task_started", task, payload={"status": task.status})
                self._persist_state_checkpoint()
            if task.role == "developer":
                developer = self._select_developer(task)
                identity = self._developer_identity(developer)
                task.context["developer_assignment"] = identity
                self._emit_event("developer_assigned", task, payload=identity)
                workflow = create_task_workflow(
                    task_manager=self.task_manager,
                    agent_router=self.agent_router,
                    state_change_hook=self._persist_state_checkpoint,
                    workflow_event_log=self._workflow_event_sink,
                    project_id=self._project_id,
                    developer=developer,
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
        except _CheckpointFailure:
            raise
        except Exception as exc:
            if task.status in {"running", "reviewing", "review_pending", "failed"}:
                if task.status != "failed":
                    self.task_manager.mark_failed(task.id, f"{type(exc).__name__}: {exc}")
                self._emit_event("task_failed", task, payload={"status": task.status, "error": task.error})
            self._apply_retry_policy(task, exc)
            self._persist_state_checkpoint()
            print(f"[Failed] {task.id}: {exc}")

    def _apply_retry_policy(self, task, error: BaseException) -> bool:
        if task.status != "failed":
            return False
        failure_kind = self.failure_classifier(error)
        if not isinstance(failure_kind, FailureKind):
            raise TypeError("failure_classifier must return FailureKind")

        reason = f"{type(error).__name__}: {error}"
        classification = classify_failure(
            failure_class=self._failure_class_for_kind(failure_kind),
            reason=reason,
        )
        decision = decide_recovery(
            classification,
            retry_attempt=task.retry_attempt,
            max_retries=task.max_retries,
        )
        if decision.action is RecoveryAction.RETRY:
            self.failure_recovery_executor.execute(task.id, decision)
            self._emit_event("task_retrying", task, payload={
                "status": task.status, "retry_attempt": task.retry_attempt,
                "max_retries": task.max_retries, "reason": decision.failure_reason or decision.reason,
            })
            return True
        if decision.action is RecoveryAction.REPLAN:
            if self._replan_coordinator is None:
                return False
            intent = RecoveryIntent(
                action=decision.action,
                task_id=task.id,
                failure_class=decision.failure_class,
                failure_reason=decision.failure_reason or reason,
                decision_reason=decision.reason,
                attempt=decision.retry_attempt,
            )
            requirement = f"{task.description}\n\nRecovery reason: {reason}"
            outcome = self._replan_coordinator.prepare(intent, requirement)
            self._replan_coordinator.commit(outcome)
            self._emit_event("task_replanned", task, payload={
                "status": task.status,
                "attempt": outcome.result.attempt,
                "task_count": len(outcome.replacement.tasks),
            })
            return True
        return False

    def _handle_no_ready_tasks(self) -> None:
        print("\n[ERROR] 没有可以执行的任务。\n")
        print("当前任务状态：")
        for task in self.task_manager.get_all_tasks():
            error = f" | {task.error}" if task.error else ""
            print(f"{task.id:<10}{task.status:<14}{task.role:<12}{task.title}{error}")