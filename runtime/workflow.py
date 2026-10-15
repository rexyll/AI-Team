from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.result_normalizer import normalize_agent_result
from runtime.context_builder import build_task_context
from runtime.workflow_transition import WorkflowOutcomeKind, get_workflow_transition
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.evidence_gate import EvidenceGateError
from runtime.gate_evidence import validate_reviewer_gate_evidence, validate_tester_gate_evidence
from runtime.provenance import agent_feedback_provenance, provenance_from_value
from enum import Enum
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from runtime.agent_result import AgentResult

MAX_REVIEW_ROUNDS = 3
MAX_REVIEWER_RECOVERY_ATTEMPTS = 1


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
        return {} if self.result is None else self.result.to_dict()

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
        max_reviewer_recovery_attempts: int = MAX_REVIEWER_RECOVERY_ATTEMPTS,
        execution_id: str | None = None,
    ):
        if max_review_rounds <= 0:
            raise ValueError("max_review_rounds must be greater than 0")
        if max_reviewer_recovery_attempts < 0:
            raise ValueError("max_reviewer_recovery_attempts must be >= 0")
        if state_change_hook is not None and not callable(state_change_hook):
            raise TypeError("state_change_hook must be callable or None")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        if execution_id is not None and (not isinstance(execution_id, str) or not execution_id.strip()):
            raise ValueError("execution_id must be a non-empty string or None")

        self.task_manager = task_manager
        self.agent_router = agent_router
        self.max_review_rounds = max_review_rounds
        self.max_reviewer_recovery_attempts = max_reviewer_recovery_attempts
        self._state_change_hook = state_change_hook
        self._workflow_event_log = workflow_event_log
        self._project_id = project_id
        self._developer = developer
        self._reviewer = reviewer
        self._tester = tester
        self._execution_id = execution_id.strip() if isinstance(execution_id, str) else None
        self._last_checkpoint_status: str | None = None

        self._validate_explicit_agent("developer", developer)
        self._validate_explicit_agent("reviewer", reviewer)
        if tester is not None:
            self._validate_explicit_agent("tester", tester)

    def _validate_explicit_agent(self, role: str, agent) -> None:
        if agent is None:
            return
        get_developers = getattr(self.agent_router, "get_developers", None)
        get_agent = getattr(self.agent_router, "get_agent", None)
        if role == "developer":
            if not callable(get_developers) and not callable(get_agent):
                return
            if callable(get_developers) and agent in get_developers():
                return
            if callable(get_agent) and agent is get_agent(role):
                return
            raise ValueError("TaskWorkflow developer agent must be the instance registered by the router")
        if not callable(get_agent):
            return
        registered = get_agent(role)
        if registered is None:
            raise ValueError(f"No agent registered for role: {role}")
        if agent is not registered:
            raise ValueError(f"TaskWorkflow {role} agent must be the instance registered by the router")

    def _agent(self, role: str, fallback=None):
        get_agent = getattr(self.agent_router, "get_agent", None)
        if callable(get_agent):
            agent = get_agent(role)
            if agent is not None:
                return agent
        return fallback

    @property
    def developer(self):
        get_developers = getattr(self.agent_router, "get_developers", None)
        if callable(get_developers):
            pool = get_developers()
            if self._developer in pool:
                return self._developer
        return self._agent("developer", self._developer)

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
        event_payload = dict(payload or {})
        if self._execution_id is not None:
            event_payload.setdefault("execution_id", self._execution_id)
        self._workflow_event_log.append(WorkflowEvent(
            event_id=str(uuid4()), event_type=event_type, project_id=project_id,
            task_id=task.id, occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            payload=event_payload,
        ))

    def _capture_developer_tool_history(self, task: Task) -> None:
        history = getattr(self.developer, "tool_execution_history", None)
        if history is None or not hasattr(history, "to_dict"):
            return
        task.context["tool_execution_history"] = history.to_dict()

    def _capture_reviewer_feedback(self, task: Task, feedback: dict[str, Any]) -> None:
        task.context["reviewer_feedback"] = feedback

    @staticmethod
    def _require_direct_parent(chain, expected_parent: Any, *, stage: str) -> None:
        expected = provenance_from_value(expected_parent)
        if expected is None:
            raise EvidenceGateError(f"{stage} gate is missing its required parent evidence")
        if len(chain) < 2 or chain[1].evidence_id != expected.evidence_id:
            raise EvidenceGateError(f"{stage} gate evidence is not linked to current parent evidence")

    @staticmethod
    def _attest_stage_feedback(outcome: StageOutcome, *, stage: str) -> None:
        """Attest legacy stage results only when crossing the gate boundary."""
        if outcome.result is None:
            return
        data = dict(outcome.result.data)
        if isinstance(data.get("provenance"), dict):
            return
        evidence_id = f"{stage}:{outcome.result.task_id}"
        parent_evidence_id = f"developer:{outcome.result.task_id}" if stage == "tester" else f"tester:{outcome.result.task_id}"
        data["provenance"] = agent_feedback_provenance(
            task_id=outcome.result.task_id,
            agent_role=stage,
            evidence_id=evidence_id,
            parent_evidence_id=parent_evidence_id,
        ).to_dict()
        outcome.result = AgentResult(
            status=outcome.result.status,
            agent=outcome.result.agent,
            task_id=outcome.result.task_id,
            message=outcome.result.message,
            data=data,
        )

    def _validate_tester_gate_outcome(self, task: Task, outcome: StageOutcome) -> None:
        developer_result = task.result
        if not developer_result:
            return
        chain = validate_tester_gate_evidence(outcome.result_dict, task_id=task.id, parents=(developer_result,))
        self._require_direct_parent(chain, developer_result, stage="tester")

    def _validate_reviewer_gate_outcome(self, task: Task, outcome: StageOutcome) -> None:
        tester_feedback = task.context.get("tester_feedback")
        parent_values = []
        if tester_feedback:
            parent_values.append(tester_feedback)
        if task.result:
            parent_values.append(task.result)
        if not parent_values:
            return
        chain = validate_reviewer_gate_evidence(outcome.result_dict, task_id=task.id, parents=tuple(parent_values))
        if self.tester is not None:
            self._require_direct_parent(chain, tester_feedback, stage="reviewer")

    def _run_gate_with_invalid_tolerance(self, run_gate, *, stage: str):
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

    def execute(self, task_id: str, *, execution_id: str | None = None) -> Task:
        if execution_id is not None:
            if not isinstance(execution_id, str) or not execution_id.strip():
                raise ValueError("execution_id must be a non-empty string or None")
            normalized_execution_id = execution_id.strip()
            if self._execution_id is not None and self._execution_id != normalized_execution_id:
                raise ValueError("execution_id conflicts with workflow execution identity")
            self._execution_id = normalized_execution_id
        if self._execution_id is None:
            self._execution_id = str(uuid4())
        task = self.task_manager.ensure_executable(task_id)
        task.context["execution_id"] = self._execution_id
        last_gate_note = "unknown"
        for round_index in range(1, self.max_review_rounds + 1):
            if task.status == "ready":
                self.task_manager.mark_running(task_id)
                self._emit_event("task_started", task, payload={"status": task.status})
                self._checkpoint()
            self._build_context(task)
            developer_outcome = self._run_developer(task)
            self._capture_developer_tool_history(task)
            result_data = developer_outcome.result.data if developer_outcome.result is not None else None
            guard = result_data.get("tool_loop_guard", {}) if isinstance(result_data, dict) else {}
            if isinstance(guard, dict) and guard.get("tripped") and round_index < self.max_review_rounds:
                # A progress-guard trip is stochastic model behavior, not a
                # deterministic failure. Intercept it before the failure
                # outcome marks the task failed: the task stays RUNNING and
                # the next round retries with the guard reason as feedback.
                reason = str(guard.get("reason") or "tool loop made no progress")
                last_gate_note = f"进度守卫拦截并重试（第 {round_index} 轮）"
                self.task_manager.set_feedback(
                    task.id,
                    "reviewer",
                    {
                        "decision": "retry",
                        "summary": (
                            f"上一轮被进度守卫拦截：{reason}。"
                            "请调整策略，避免重复无进展的调用。"
                        ),
                    },
                )
                self._emit_event("developer_guard_retry", task, payload={"round": round_index, "reason": reason})
                self._checkpoint()
                print(f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: guard retry with feedback")
                continue
            self._apply_developer_outcome(task, developer_outcome)
            validation = result_data.get("validation", {}) if isinstance(result_data, dict) else {}
            dev_metrics = ""
            if validation:
                dev_metrics = f", tool_calls={validation.get('tool_call_count', '?')}, files_changed={validation.get('files_changed_count', '?')}"
            message_head = ""
            if developer_outcome.result is not None:
                raw_message = (developer_outcome.result.message or "").strip()
                message_head = raw_message.replace("\n", " ")[:120]
                if len(raw_message) > 120:
                    message_head += "…"
            print(f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: developer={developer_outcome.status}{dev_metrics} | {message_head}")
            if task.status == "failed":
                if developer_outcome.exception is not None:
                    raise developer_outcome.exception
                return task
            if self.tester is not None:
                tester_outcome = self._run_gate_with_invalid_tolerance(lambda: self._run_tester(task), stage="tester")
                self._attest_stage_feedback(tester_outcome, stage="tester")
                tester_passed = self._handle_tester_result(task, tester_outcome)
                print(f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: tester={tester_outcome.status}")
                if not tester_passed:
                    if task.status == "failed":
                        return task
                    last_gate_note = f"tester 判定未通过（status={tester_outcome.status}）"
                    verdict = tester_outcome.result.message if tester_outcome.result is not None else ""
                    print(f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: tester note: {verdict[:160]}")
                    continue
            else:
                self._transition_to_declared_target(task, "tester", WorkflowOutcomeKind.SUCCESS)
                self._emit_event("tester_skipped", task, payload={"status": task.status})
                self._checkpoint()
                print(f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: tester=skipped")
            self._emit_event("review_started", task, payload={"status": task.status})
            review_outcome = self._run_gate_with_invalid_tolerance(lambda: self._run_reviewer(task), stage="reviewer")
            self._attest_stage_feedback(review_outcome, stage="reviewer")
            review_action = self._apply_reviewer_outcome(task, review_outcome)
            print(f"[Gate] {task.id} round {round_index}/{self.max_review_rounds}: reviewer={review_outcome.status}")
            recovery_attempt = 0
            while review_action == "retry" and recovery_attempt < self.max_reviewer_recovery_attempts:
                recovery_attempt += 1
                self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.REVIEWER_RETRY)
                self._emit_event("reviewer_retry", task, payload={"attempt": recovery_attempt, "max_attempts": self.max_reviewer_recovery_attempts})
                self._checkpoint()
                self._emit_event("review_started", task, payload={"status": task.status, "recovery_attempt": recovery_attempt})
                review_outcome = self._run_gate_with_invalid_tolerance(lambda: self._run_reviewer(task), stage="reviewer")
                self._attest_stage_feedback(review_outcome, stage="reviewer")
                review_action = self._apply_reviewer_outcome(task, review_outcome)
                print(f"[Gate] {task.id} recovery {recovery_attempt}/{self.max_reviewer_recovery_attempts}: reviewer={review_outcome.status}")
            if review_action == "completed":
                return task
            if review_action == "failed":
                if review_outcome.exception is not None:
                    raise review_outcome.exception
                return task
            if review_action == "retry":
                last_gate_note = "reviewer execution recovery exhausted"
                continue
            if review_action == "revision":
                last_gate_note = f"reviewer 要求返工（第 {round_index} 轮）"
                continue
        reason = f"质量门禁在 {self.max_review_rounds} 轮内未通过（最后状态: {last_gate_note}）"
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
            try:
                self._validate_tester_gate_outcome(task, outcome)
            except EvidenceGateError as exc:
                self.task_manager.record_test_result(task.id, outcome.result_dict)
                self.task_manager.set_feedback(task.id, "tester", outcome.result)
                self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.INVALID_RESULT)
                self.task_manager.record_error(task.id, f"Tester evidence validation failed: {exc}")
                self._emit_event("tester_invalid_evidence", task, payload={**outcome.to_dict(), "error": str(exc)})
                self._checkpoint()
                return
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
            self.task_manager.set_feedback(task.id, "tester", outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._emit_event("tester_rejected", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        if outcome.status == "invalid_result":
            self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.INVALID_RESULT)
            self.task_manager.record_error(task.id, f"Invalid tester result status: {outcome.status}")
            self._emit_event("tester_invalid_result", task, payload=outcome.to_dict())
            self._checkpoint()
            return
        self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, f"Invalid tester result status: {outcome.status}")
        self._emit_event("tester_invalid_result", task, payload=outcome.to_dict())
        self._checkpoint()

    def _handle_tester_result(self, task: Task, outcome: StageOutcome) -> bool:
        self._apply_tester_outcome(task, outcome)
        return outcome.status == "passed" and outcome.exception is None and task.status == "reviewing"

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
        execution = {}
        if outcome.result is not None and isinstance(outcome.result.data, dict):
            execution = outcome.result.data.get("reviewer_execution", {})
        recovery_source = execution.get("source") == "recovery"
        if outcome.status == "approved":
            try:
                self._validate_reviewer_gate_outcome(task, outcome)
            except EvidenceGateError as exc:
                self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.INVALID_RESULT)
                self.task_manager.record_review_result(task.id, outcome.result_dict)
                self.task_manager.set_feedback(task.id, "reviewer", outcome.result_dict)
                self.task_manager.record_error(task.id, f"Reviewer evidence validation failed: {exc}")
                self._emit_event("reviewer_invalid_evidence", task, payload={**outcome.to_dict(), "error": str(exc)})
                self._checkpoint()
                return "failed"
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.SUCCESS)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._emit_event("reviewer_approved", task, payload={**outcome.to_dict(), "status": task.status})
            self._checkpoint()
            return "completed"
        if recovery_source:
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.REVIEWER_RECOVERY)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "reviewer", outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._emit_event("reviewer_fallback", task, payload=outcome.to_dict())
            self._checkpoint()
            return "retry"
        if outcome.exception is not None:
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, f"Reviewer execution failed: {outcome.exception}")
            self._emit_event("reviewer_failed", task, payload=outcome.to_dict())
            self._checkpoint()
            return "failed"
        if outcome.status == "revision":
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.REVISION_REQUIRED)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "reviewer", outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._emit_event("reviewer_revision", task, payload=outcome.to_dict())
            self._checkpoint()
            return "revision"
        self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_review_result(task.id, outcome.result_dict)
        self.task_manager.record_error(task.id, f"Invalid reviewer result status: {outcome.status}")
        self._emit_event("reviewer_invalid_result", task, payload=outcome.to_dict())
        self._checkpoint()
        return "failed"

    def _build_context(self, task: Task) -> None:
        context = build_task_context(task, self.task_manager.tasks)
        task.context["dependencies"] = context


# Install only after TaskWorkflow is fully defined. Doing this from
# runtime/__init__.py causes agents.base -> runtime.* -> workflow ->
# agent_router -> agents.base circular imports.
from runtime.workflow_root_tracing import install_workflow_root_tracing
install_workflow_root_tracing()
