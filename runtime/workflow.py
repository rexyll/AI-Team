from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.result_normalizer import normalize_agent_result
from runtime.context_builder import build_task_context
from runtime.workflow_transition import (
    WorkflowOutcomeKind,
    get_workflow_transition,
)
from enum import Enum
from dataclasses import dataclass
from typing import Any, Callable

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
    """Execute one task through Developer/Tester/Reviewer iterations.

    AgentRouter is the preferred source of truth for stage agents. The
    explicit agent arguments remain a compatibility boundary for legacy
    lightweight routers and test doubles that only expose ``route`` or no
    registry API at all. When a router exposes ``get_agent``, the resolved
    instance must match the explicit compatibility argument.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        developer,
        reviewer,
        agent_router,
        max_review_rounds: int = MAX_REVIEW_ROUNDS,
        tester=None,
        state_change_hook: Callable[[TaskManager], None] | None = None,
    ):
        if max_review_rounds <= 0:
            raise ValueError("max_review_rounds must be greater than 0")
        if agent_router is None:
            raise TypeError("agent_router is required")
        if state_change_hook is not None and not callable(state_change_hook):
            raise TypeError("state_change_hook must be callable or None")

        self.task_manager = task_manager
        self.agent_router = agent_router
        self.max_review_rounds = max_review_rounds
        self._state_change_hook = state_change_hook

        self._validate_explicit_agent("developer", developer)
        self._validate_explicit_agent("reviewer", reviewer)
        if tester is not None:
            self._validate_explicit_agent("tester", tester)

    def _validate_explicit_agent(self, role: str, agent) -> None:
        """Validate the compatibility argument without forcing a concrete router type."""
        if isinstance(self.agent_router, AgentRouter):
            registered = self.agent_router.get_agent(role)
            if registered is None:
                raise ValueError(f"No agent registered for role: {role}")
            if agent is not registered:
                raise ValueError(
                    f"TaskWorkflow {role} agent must be the instance registered in AgentRouter"
                )
            return

        get_agent = getattr(self.agent_router, "get_agent", None)
        if callable(get_agent):
            registered = get_agent(role)
            if registered is None:
                raise ValueError(f"No agent registered for role: {role}")
            if agent is not registered:
                raise ValueError(
                    f"TaskWorkflow {role} agent must match the router-resolved instance"
                )

    def _agent(self, role: str, fallback=None):
        """Resolve an agent from the router when its registry API is available."""
        get_agent = getattr(self.agent_router, "get_agent", None)
        if callable(get_agent):
            agent = get_agent(role)
            if agent is not None:
                return agent
        return fallback

    @property
    def developer(self):
        return self._agent("developer", self._developer_fallback)

    @property
    def tester(self):
        return self._agent("tester", self._tester_fallback)

    @property
    def reviewer(self):
        return self._agent("reviewer", self._reviewer_fallback)

    def _checkpoint(self) -> None:
        """Persist a workflow-stage boundary when a durable hook is installed."""
        if self._state_change_hook is not None:
            self._state_change_hook(self.task_manager)

    def _capture_developer_tool_history(self, task: Task) -> None:
        """Attach immutable Developer tool evidence to the persisted task context."""
        history = getattr(self.developer, "tool_execution_history", None)
        if history is None or not hasattr(history, "to_dict"):
            return
        task.context["tool_execution_history"] = history.to_dict()

    def execute(self, task_id: str) -> Task:
        task = self.task_manager.ensure_executable(task_id)

        for _ in range(self.max_review_rounds):
            if task.status == "ready":
                self.task_manager.mark_running(task_id)
                self._checkpoint()

            self._build_context(task)

            developer_outcome = self._run_developer(task)
            self._capture_developer_tool_history(task)
            self._apply_developer_outcome(task, developer_outcome)

            if task.status == "failed":
                return task

            if self.tester is not None:
                tester_outcome = self._run_tester(task)
                if not self._handle_tester_result(task, tester_outcome):
                    if task.status == "failed":
                        return task
                    if tester_outcome.status != "passed":
                        continue
            else:
                self._transition_to_declared_target(task, "tester", WorkflowOutcomeKind.SUCCESS)
                self._checkpoint()

            review_outcome = self._run_reviewer(task)
            review_action = self._apply_reviewer_outcome(task, review_outcome)

            if review_action == "completed":
                return task
            if review_action == "failed":
                return task
            if review_action == "revision":
                continue

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
            self._checkpoint()
            return
        if outcome.exception is not None:
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_error(task.id, outcome.result_dict.get("message", "Tester execution failed"))
            self._checkpoint()
            return
        if outcome.status == "failed":
            self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.QUALITY_GATE_FAILURE)
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "tester", outcome.result)
            self.task_manager.record_error(task.id, None)
            self._checkpoint()
            return
        self._transition_for_outcome(task, WorkflowStage.TESTER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, f"Invalid tester result status: {outcome.status}")
        self._checkpoint()

    def _handle_tester_result(self, task: Task, outcome: StageOutcome) -> bool:
        self._apply_tester_outcome(task, outcome)
        return outcome.status == "passed"

    def _run_developer(self, task: Task) -> StageOutcome:
        try:
            raw_result = self.developer.run(task)
            result = normalize_agent_result(raw_result)
            return StageOutcome.success(WorkflowStage.DEVELOPER, result)
        except Exception as exc:
            return StageOutcome.failure(WorkflowStage.DEVELOPER, exc)

    def _apply_developer_outcome(self, task: Task, outcome: StageOutcome) -> None:
        if outcome.exception is not None:
            error = f"Developer execution failed: {outcome.exception}"
            self._transition_for_outcome(task, WorkflowStage.DEVELOPER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_error(task.id, error)
            self._checkpoint()
            raise outcome.exception
        if outcome.status == "completed":
            self._transition_for_outcome(task, WorkflowStage.DEVELOPER, WorkflowOutcomeKind.SUCCESS)
            self.task_manager.record_error(task.id, None)
            self.task_manager.record_result(task.id, outcome.result_dict)
            self._checkpoint()
            return
        message = outcome.result.message if outcome.result is not None else "Developer execution failed"
        self._transition_for_outcome(task, WorkflowStage.DEVELOPER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, message)
        self._checkpoint()

    def _run_reviewer(self, task: Task) -> StageOutcome:
        try:
            raw_result = self.reviewer.run(task)
            result = normalize_agent_result(raw_result)
            return StageOutcome.success(WorkflowStage.REVIEWER, result)
        except Exception as exc:
            return StageOutcome.failure(WorkflowStage.REVIEWER, exc)

    def _apply_reviewer_outcome(self, task: Task, outcome: StageOutcome) -> str:
        if task.status == "review_pending":
            self._transition_to_declared_target(task, "tester", WorkflowOutcomeKind.SUCCESS)
            self._checkpoint()
        if outcome.exception is not None:
            error = f"Reviewer execution failed: {outcome.exception}"
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_error(task.id, error)
            self._checkpoint()
            raise outcome.exception
        if outcome.status == "approved":
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.SUCCESS)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            self._checkpoint()
            return "completed"
        if outcome.status == "revision":
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.QUALITY_GATE_FAILURE)
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "reviewer", outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            if task.review_round >= self.max_review_rounds:
                self.task_manager.mark_failed(task.id, f"Task failed review after {self.max_review_rounds} rounds")
                self._checkpoint()
                return "failed"
            self._checkpoint()
            return "revision"
        if outcome.status == "failed":
            message = outcome.result.message if outcome.result is not None else "Reviewer execution failed"
            self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.EXECUTION_FAILURE)
            self.task_manager.record_error(task.id, message)
            self._checkpoint()
            return "failed"
        self._transition_for_outcome(task, WorkflowStage.REVIEWER, WorkflowOutcomeKind.INVALID_RESULT)
        self.task_manager.record_error(task.id, f"Unknown reviewer status: {outcome.status}")
        self._checkpoint()
        return "failed"

    def _handle_review_result(self, task: Task, outcome: StageOutcome) -> str:
        if outcome.status == "approved":
            return "completed"
        if outcome.status == "failed":
            return "failed"
        if outcome.status == "revision":
            if task.review_round >= self.max_review_rounds:
                self.task_manager.mark_failed(task.id, f"Task failed review after {self.max_review_rounds} rounds")
                return "failed"
            return "revision"
        self.task_manager.mark_failed(task.id, f"Unknown review status: {outcome.status}")
        return "failed"

    def _build_context(self, task: Task) -> None:
        """Build and persist dependency context for the current task."""
        all_tasks = {item.id: item for item in self.task_manager.get_all_tasks()}
        dependency_context = build_task_context(task, all_tasks)
        task.context["dependencies"] = dependency_context
