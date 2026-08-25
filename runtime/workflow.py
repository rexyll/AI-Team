from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.result_normalizer import normalize_agent_result
from runtime.context_builder import build_task_context
from runtime.workflow_transition import (
    WorkflowOutcomeKind,
    get_workflow_transition,
)
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from enum import Enum
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from runtime.agent_result import AgentResult


MAX_REVIEW_ROUNDS = 3


@dataclass
class StageOutcome:
    """Unified result contract for one workflow stage."""

    stage: "WorkflowStage"
    status: str
    result: AgentResult | dict[str, Any] | None = None
    exception: Exception | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, WorkflowStage):
            raise TypeError("stage must be a WorkflowStage")
        if not isinstance(self.status, str):
            raise TypeError("status must be a string")
        self.status = self.status.strip()
        if not self.status:
            raise ValueError("status must be a non-empty string")
        if self.exception is not None and not isinstance(self.exception, Exception):
            raise TypeError("exception must be an Exception or None")
        if isinstance(self.result, dict):
            self.result = self._normalize_result(self.result)
        if self.result is not None and not isinstance(self.result, AgentResult):
            raise TypeError("result must be an AgentResult, dict, or None")
        if self.result is not None:
            self.status = self.result.status
        if self.exception is not None:
            self.status = "failed"

    @staticmethod
    def _normalize_result(result: dict[str, Any]) -> AgentResult:
        payload = dict(result)
        payload.setdefault("agent", "unknown")
        payload.setdefault("task_id", "unknown")
        return AgentResult.from_dict(payload)

    @classmethod
    def success(cls, stage: "WorkflowStage", result: AgentResult) -> "StageOutcome":
        if not isinstance(result, AgentResult):
            raise TypeError("StageOutcome.success requires an AgentResult")
        return cls(stage=stage, status=result.status, result=result, exception=None)

    @classmethod
    def failure(cls, stage: "WorkflowStage", exception: Exception) -> "StageOutcome":
        if not isinstance(exception, Exception):
            raise TypeError("StageOutcome.failure requires an Exception")
        return cls(stage=stage, status="failed", result=None, exception=exception)

    @property
    def result_dict(self) -> dict[str, Any]:
        if self.result is None:
            return {}
        return self.result.to_dict()

    @property
    def succeeded(self) -> bool:
        return self.exception is None and self.result is not None and self.status != "failed"

    @property
    def failed(self) -> bool:
        return self.status == "failed" or self.exception is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status,
            "result": self.result_dict,
            "exception": str(self.exception) if self.exception is not None else None,
        }


class WorkflowStage(str, Enum):
    DEVELOPER = "developer"
    TESTER = "tester"
    REVIEWER = "reviewer"


class TaskWorkflow:
    """Execute one task through Developer/Tester/Reviewer iterations."""

    def __init__(
        self,
        task_manager: TaskManager,
        developer,
        reviewer,
        agent_router: AgentRouter,
        max_review_rounds: int = MAX_REVIEW_ROUNDS,
        tester=None,
        state_change_hook: Callable[[TaskManager], None] | None = None,
        workflow_event_log: WorkflowEventLog | None = None,
        project_id: str | None = None,
    ):
        if max_review_rounds <= 0:
            raise ValueError("max_review_rounds must be greater than 0")
        if state_change_hook is not None and not callable(state_change_hook):
            raise TypeError("state_change_hook must be callable or None")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")

        self.task_manager = task_manager
        self.agent_router = agent_router
        self.max_review_rounds = max_review_rounds
        self._state_change_hook = state_change_hook
        self._workflow_event_log = workflow_event_log
        self._project_id = project_id
        self._developer = developer
        self._reviewer = reviewer
        self._tester = tester
        self._last_checkpoint_status: str | None = None

        self._validate_explicit_agent("developer", developer)
        self._validate_explicit_agent("reviewer", reviewer)
        if tester is not None:
            self._validate_explicit_agent("tester", tester)

    def _validate_explicit_agent(self, role: str, agent) -> None:
        if agent is None:
            return
        if role == "developer":
            get_developers = getattr(self.agent_router, "get_developers", None)
            if callable(get_developers):
                pool = get_developers()
                if agent in pool:
                    return
            get_agent = getattr(self.agent_router, "get_agent", None)
            if callable(get_agent) and agent is get_agent(role):
                return
            raise ValueError(
                "TaskWorkflow developer agent must belong to the router's Developer pool"
            )

        get_agent = getattr(self.agent_router, "get_agent", None)
        if not callable(get_agent):
            return
        registered = get_agent(role)
        if registered is None:
            raise ValueError(f"No agent registered for role: {role}")
        if agent is not registered:
            raise ValueError(
                f"TaskWorkflow {role} agent must be the instance registered by the router"
            )

    def _agent(self, role: str, fallback=None):
        get_agent = getattr(self.agent_router, "get_agent", None)
        if callable(get_agent):
            agent = get_agent(role)
            if agent is not None:
                return agent
        return fallback

    @property
    def developer(self):
        return self._developer

    @property
    def tester(self):
        return self._agent("tester", self._tester)

    @property
    def reviewer(self):
        return self._agent("reviewer", self._reviewer)

    def _checkpoint(self) -> None:
        if self._state_change_hook is None:
            return
        task_statuses = [task.status for task in self.task_manager.get_all_tasks()]
        current_status = task_statuses[0] if len(task_statuses) == 1 else None
        if current_status is not None and current_status == self._last_checkpoint_status:
            return
        if current_status is not None:
            self._last_checkpoint_status = current_status
        self._state_change_hook(self.task_manager)

    def _emit_event(self, event_type: str, task: Task, *, payload: dict[str, Any] | None = None) -> None:
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

    def _capture_developer_tool_history(self, task: Task) -> None:
        history = getattr(self.developer, "tool_execution_history", None)
        if history is None or not hasattr(history, "to_dict"):
            return
        task.context["tool_execution_history"] = history.to_dict()

    def _run_gate_with_invalid_tolerance(self, run_gate, *, stage: str):
        """Run one gate stage, tolerating transient invalid verdict shapes."""
        try:
            extra_attempts = max(0, int(os.getenv("LLM_INVALID_VERDICT_ATTEMPTS", "2")))
        except ValueError:
            extra_attempts = 2

        outcome = run_gate()
        for _ in range(extra_attempts):
            if outcome.exception is not None:
                break
            if stage == "tester" and outcome.status in ("passed", "failed"):
                break
            if stage == "reviewer" and outcome.status in ("approved", "revision", "failed"):
                break
            print(f"[Gate] {stage}=invalid({outcome.status}); retrying with fresh completion")
            outcome = run_gate()
        return outcome

    def execute(self, task_id: str) -> Task:
        task = self.task_manager.ensure_executable(task_id)
        last_gate_note = "unknown"

        for round_index in range(1, self.max_review_rounds + 1):
            if task.status == "ready":
                self.task_manager.mark_running(task_id)
                self._emit_event("task_started", task, payload={"status": task.status})
                self._checkpoint()

            self._build_context(task)
            developer_outcome = self._run_developer(task)
            self._capture_developer_tool_history(task)
            self._apply_developer_outcome(task, developer_outcome)
            result_data = developer_outcome.result.data if developer_outcome.result is not None else None
            validation = result_data.get("validation", {}) if isinstance(result_data, dict) else {}
            dev_metrics = ""
            if validation:
                dev_metrics = (
                    f", tool_calls={validation.get('tool_call_count', '?')}, "
                    f"files_changed={validation.get('files_changed_count', '?')}"
                )
            message_head = ""
            if developer_outcome.result is not None:
                raw_message = (developer_outcome.result.message or "").strip()
                message_head = raw_message.replace("\n", " ")[:120]
                if len(raw_message) > 120:
                    message_head += "…"
            print(
                f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: "
                f"developer={developer_outcome.status}{dev_metrics} | {message_head}"
            )

            if task.status == "failed":
                return task

            if self.tester is not None:
                tester_outcome = self._run_gate_with_invalid_tolerance(
                    lambda: self._run_tester(task), stage="tester"
                )
                tester_passed = self._handle_tester_result(task, tester_outcome)
                print(
                    f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: "
                    f"tester={tester_outcome.status}"
                )
                if not tester_passed:
                    if task.status == "failed":
                        return task
                    last_gate_note = f"tester 判定未通过（status={tester_outcome.status}）"
                    verdict = tester_outcome.result.message if tester_outcome.result is not None else ""
                    print(
                        f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: "
                        f"tester note: {verdict[:160]}"
                    )
                    continue
            else:
                self._transition_to_declared_target(task, "tester", WorkflowOutcomeKind.SUCCESS)
                self._emit_event("tester_skipped", task, payload={"status": task.status})
                self._checkpoint()
                print(
                    f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: tester=skipped"
                )

            self._emit_event("review_started", task, payload={"status": task.status})
            review_outcome = self._run_gate_with_invalid_tolerance(
                lambda: self._run_reviewer(task), stage="reviewer"
            )
            review_action = self._apply_reviewer_outcome(task, review_outcome)
            print(
                f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: "
                f"reviewer={review_outcome.status}"
            )

            if review_action == "completed":
                return task
            if review_action == "failed":
                return task
            if review_action == "revision":
                last_gate_note = f"reviewer 要求返工（第 {round_index} 轮）"
                continue

        reason = (
            f"质量门禁在 {self.max_review_rounds} 轮内未通过"
            f"（最后状态: {last_gate_note}）"
        )
        print(f"[Gate] {task.id}: {reason}")
        self.task_manager.record_error(task.id, reason)
        self.task_manager.mark_failed(task.id, reason)
        self._emit_event("task_failed", task, payload={"status": task.status, "error": reason})
        self._checkpoint()
        return task

    def _transition_to_declared_target(self, task: Task, stage: str, outcome: WorkflowOutcomeKind) -> None:
        transition = get_workflow_transition(stage, outcome)
        self.task_manager.transition(task.id, transition.target)

    def _transition_for_outcome(self, task: Task, stage: WorkflowStage, outcome: WorkflowOutcomeKind) -> None:
        transition = get_workflow_transition(stage.value, outcome)
        self.task_manager.transition(task.id, transition.target)

    def _run_tester(self, task: Task) -> StageOutcome:
        try:
            raw_result = self.tester.run(task)
            result = normalize_agent_result(raw_result)
            return StageOutcome.success(WorkflowStage.TESTER, result)
        except Exception as exc:
            return StageOutcome.failure(WorkflowStage.TESTER, exc)

    def _apply_tester_outcome(self, task: Task, outcome: StageOutcome) -> None:
        if outcome.status == "passed":
            self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.SUCCESS)
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "tester", outcome.result)
            self._emit_event("tester_passed", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        if outcome.exception is not None:
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_error(task.id, f"Tester execution failed: {outcome.exception}")
            self._emit_event("tester_failed", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        if outcome.status == "failed":
            self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.QUALITY_GATE_FAILURE)
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "tester", outcome.result)
            self.task_manager.record_error(task.id, None)
            self._emit_event("tester_rejected", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, f"Invalid tester result status: {outcome.status}")
        self._emit_event("tester_invalid_result", task, payload=outcome.to_dict())
        self._checkpoint()

    def _handle_tester_result(self, task: Task, outcome: StageOutcome) -> bool:
        self._apply_tester_outcome(task, outcome)
        return outcome.status == "passed" and outcome.exception is None

    def _run_developer(self, task: Task) -> StageOutcome:
        try:
            raw_result = self.developer.run(task)
            result = normalize_agent_result(raw_result)
            return StageOutcome.success(WorkflowStage.DEVELOPER, result)
        except Exception as exc:
            return StageOutcome.failure(WorkflowStage.DEVELOPER, exc)

    def _apply_developer_outcome(self, task: Task, outcome: StageOutcome) -> None:
        if outcome.status == "completed":
            self._transition_for_outcome(task, WorkflowStage.DEVELOPER, WorkflowOutcomeKind.SUCCESS)
            self.task_manager.record_result(task.id, outcome.result_dict)
            self._emit_event("developer_completed", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        if outcome.exception is not None:
            self._transition_for_outcome(task, WorkflowStage.DEVELOPER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_error(task.id, f"Developer execution failed: {outcome.exception}")
            self._emit_event("developer_failed", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        self._transition_for_outcome(task, WorkflowStage.DEVELOPER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, f"Invalid developer result status: {outcome.status}")
        self._emit_event("developer_invalid_result", task, payload=outcome.to_dict())
        self._checkpoint()

    def _run_reviewer(self, task: Task) -> StageOutcome:
        try:
            raw_result = self.reviewer.run(task)
            result = normalize_agent_result(raw_result)
            return StageOutcome.success(WorkflowStage.REVIEWER, result)
        except Exception as exc:
            return StageOutcome.failure(WorkflowStage.REVIEWER, exc)

    def _apply_reviewer_outcome(self, task: Task, outcome: StageOutcome) -> str:
        if outcome.status == "approved":
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.SUCCESS)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._emit_event("review_approved", task, payload=outcome.to_dict())
            self._checkpoint()
            return "completed"
        if outcome.exception is not None:
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, f"Reviewer execution failed: {outcome.exception}")
            self._emit_event("review_failed", task, payload=outcome.to_dict())
            self._checkpoint()
            return "failed"
        if outcome.status == "revision":
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.REVISION_REQUIRED)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._emit_event("review_revision", task, payload=outcome.to_dict())
            self._checkpoint()
            return "revision"
        self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, f"Invalid reviewer result status: {outcome.status}")
        self._emit_event("review_invalid_result", task, payload=outcome.to_dict())
        self._checkpoint()
        return "failed"

    def _build_context(self, task: Task) -> None:
        context = build_task_context(task, self.task_manager.tasks)
        if isinstance(context, dict):
            task.context["dependencies"] = context
