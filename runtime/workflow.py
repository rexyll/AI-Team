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
from typing import Any

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
    ):
        if max_review_rounds <= 0:
            raise ValueError("max_review_rounds must be greater than 0")
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.developer = developer
        self.tester = tester
        self.reviewer = reviewer
        self.max_review_rounds = max_review_rounds

    def execute(self, task_id: str) -> Task:
        task = self.task_manager.ensure_executable(task_id)

        for _ in range(self.max_review_rounds):
            if task.status == "ready":
                self.task_manager.mark_running(task_id)

            self._build_context(task)

            developer_outcome = self._run_developer(task)
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
                # A no-tester workflow still needs the reviewer entry state.
                # Reuse the declared Tester success target rather than
                # duplicating review_pending -> reviewing topology here.
                self._transition_to_declared_target(
                    task,
                    "tester",
                    WorkflowOutcomeKind.SUCCESS,
                )

            review_outcome = self._run_reviewer(task)
            review_action = self._apply_reviewer_outcome(task, review_outcome)

            if review_action == "completed":
                return task
            if review_action == "failed":
                return task
            if review_action == "revision":
                continue

        return task

    def _transition_to_declared_target(
        self,
        task: Task,
        stage: str,
        outcome: WorkflowOutcomeKind,
    ) -> None:
        """Apply the target declared by the workflow transition contract."""
        transition = get_workflow_transition(stage, outcome)
        self.task_manager.transition(task.id, transition.target)

    def _transition_for_outcome(
        self,
        task: Task,
        stage: WorkflowStage,
        outcome: WorkflowOutcomeKind,
    ) -> None:
        """Apply a stage outcome through the single declarative transition source."""
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
            self._transition_for_outcome(
                task,
                WorkflowStage.TESTER,
                WorkflowOutcomeKind.SUCCESS,
            )
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "tester", outcome.result)
            return

        if outcome.exception is not None:
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self._transition_for_outcome(
                task,
                WorkflowStage.TESTER,
                WorkflowOutcomeKind.EXECUTION_FAILURE,
            )
            self.task_manager.record_error(
                task.id,
                outcome.result_dict.get("message", "Tester execution failed"),
            )
            return

        if outcome.status == "failed":
            self._transition_for_outcome(
                task,
                WorkflowStage.TESTER,
                WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
            )
            self.task_manager.record_test_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "tester", outcome.result)
            self.task_manager.record_error(task.id, None)
            return

        self._transition_for_outcome(
            task,
            WorkflowStage.TESTER,
            WorkflowOutcomeKind.INVALID_RESULT,
        )
        self.task_manager.record_error(
            task.id,
            f"Invalid tester result status: {outcome.status}",
        )

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
            self._transition_for_outcome(
                task,
                WorkflowStage.DEVELOPER,
                WorkflowOutcomeKind.EXECUTION_FAILURE,
            )
            self.task_manager.record_error(task.id, error)
            raise outcome.exception

        if outcome.status == "completed":
            self._transition_for_outcome(
                task,
                WorkflowStage.DEVELOPER,
                WorkflowOutcomeKind.SUCCESS,
            )
            self.task_manager.record_error(task.id, None)
            self.task_manager.record_result(task.id, outcome.result_dict)
            return

        message = (
            outcome.result.message
            if outcome.result is not None
            else "Developer execution failed"
        )
        self._transition_for_outcome(
            task,
            WorkflowStage.DEVELOPER,
            WorkflowOutcomeKind.INVALID_RESULT,
        )
        self.task_manager.record_error(task.id, message)

    def _run_reviewer(self, task: Task) -> StageOutcome:
        try:
            raw_result = self.reviewer.run(task)
            result = normalize_agent_result(raw_result)
            return StageOutcome.success(WorkflowStage.REVIEWER, result)
        except Exception as exc:
            return StageOutcome.failure(WorkflowStage.REVIEWER, exc)

    def _apply_reviewer_outcome(self, task: Task, outcome: StageOutcome) -> str:
        if task.status == "review_pending":
            self._transition_to_declared_target(
                task,
                "tester",
                WorkflowOutcomeKind.SUCCESS,
            )

        if outcome.exception is not None:
            error = f"Reviewer execution failed: {outcome.exception}"
            self._transition_for_outcome(
                task,
                WorkflowStage.REVIEWER,
                WorkflowOutcomeKind.EXECUTION_FAILURE,
            )
            self.task_manager.record_error(task.id, error)
            raise outcome.exception

        if outcome.status == "approved":
            self._transition_for_outcome(
                task,
                WorkflowStage.REVIEWER,
                WorkflowOutcomeKind.SUCCESS,
            )
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.record_error(task.id, None)
            return "completed"

        if outcome.status == "revision":
            self._transition_for_outcome(
                task,
                WorkflowStage.REVIEWER,
                WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
            )
            self.task_manager.record_review_result(task.id, outcome.result_dict)
            self.task_manager.set_feedback(task.id, "reviewer", outcome.result_dict)
            self.task_manager.record_error(task.id, None)

            if task.review_round >= self.max_review_rounds:
                self.task_manager.mark_failed(
                    task.id,
                    f"Task failed review after {self.max_review_rounds} rounds",
                )
                return "failed"

            return "revision"

        if outcome.status == "failed":
            message = (
                outcome.result.message
                if outcome.result is not None
                else "Reviewer execution failed"
            )
            self._transition_for_outcome(
                task,
                WorkflowStage.REVIEWER,
                WorkflowOutcomeKind.EXECUTION_FAILURE,
            )
            self.task_manager.record_error(task.id, message)
            return "failed"

        self._transition_for_outcome(
            task,
            WorkflowStage.REVIEWER,
            WorkflowOutcomeKind.INVALID_RESULT,
        )
        self.task_manager.record_error(
            task.id,
            f"Unknown reviewer status: {outcome.status}",
        )
        return "failed"

    def _handle_review_result(self, task: Task, outcome: StageOutcome) -> str:
        if outcome.status == "approved":
            return "completed"

        if outcome.status == "failed":
            return "failed"

        if outcome.status == "revision":
            if task.review_round >= self.max_review_rounds:
                self.task_manager.mark_failed(
                    task.id,
                    f"Task failed review after {self.max_review_rounds} rounds",
                )
                return "failed"
            return "revision"

        self.task_manager.mark_failed(
            task.id,
            f"Unknown review status: {outcome.status}",
        )
        return "failed"

    def _build_context(self, task: Task) -> None:
        """Build and persist dependency context for the current task."""
        all_tasks = {item.id: item for item in self.task_manager.get_all_tasks()}
        dependency_context = build_task_context(task, all_tasks)
        task.context["dependencies"] = dependency_context
