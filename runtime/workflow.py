from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.result_normalizer import normalize_agent_result
from runtime.context_builder import build_task_context
from enum import Enum
from dataclasses import dataclass
from typing import Any

from runtime.task_status import TaskStatus
from runtime.agent_result import AgentResult


MAX_REVIEW_ROUNDS = 3


@dataclass
class StageOutcome:
    """
    Unified result contract for one workflow stage.

    A StageOutcome represents the execution result of exactly one
    WorkflowStage.

    Contract:

        stage
        status
        result
        exception
        result_dict

    ``result`` is always the canonical AgentResult when the stage
    completed successfully.

    ``result_dict`` is a compatibility/read-only representation of
    ``result`` in canonical dictionary form.

    ``exception`` is populated only when stage execution failed.
    """

    stage: WorkflowStage
    status: str
    result: AgentResult | dict[str, Any] | None = None
    exception: Exception | None = None

    def __post_init__(self) -> None:
        # ------------------------------------------------------------
        # stage
        # ------------------------------------------------------------
        if not isinstance(self.stage, WorkflowStage):
            raise TypeError(
                "stage must be a WorkflowStage"
            )

        # ------------------------------------------------------------
        # status
        # ------------------------------------------------------------
        if not isinstance(self.status, str):
            raise TypeError(
                "status must be a string"
            )

        self.status = self.status.strip()

        if not self.status:
            raise ValueError(
                "status must be a non-empty string"
            )

        # ------------------------------------------------------------
        # exception
        # ------------------------------------------------------------
        if (
            self.exception is not None
            and not isinstance(self.exception, Exception)
        ):
            raise TypeError(
                "exception must be an Exception or None"
            )

        # ------------------------------------------------------------
        # result
        #
        # Accept both:
        #
        # 1. canonical AgentResult
        # 2. legacy dictionary
        #
        # This allows Workflow-level compatibility without weakening
        # the AgentResult contract itself.
        # ------------------------------------------------------------
        if isinstance(self.result, dict):
            self.result = self._normalize_result(
                self.result
            )

        if (
            self.result is not None
            and not isinstance(self.result, AgentResult)
        ):
            raise TypeError(
                "result must be an AgentResult, dict, or None"
            )

        # ------------------------------------------------------------
        # Canonical status
        #
        # The AgentResult is the source of truth for successful
        # execution. Do not allow StageOutcome.status to diverge.
        # ------------------------------------------------------------
        if self.result is not None:
            self.status = self.result.status

        # ------------------------------------------------------------
        # Failure consistency
        # ------------------------------------------------------------
        if self.exception is not None:
            self.status = "failed"

    # ----------------------------------------------------------------
    # Result normalization
    # ----------------------------------------------------------------

    @staticmethod
    def _normalize_result(
        result: dict[str, Any],
    ) -> AgentResult:
        """
        Normalize a legacy result dictionary into AgentResult.

        StageOutcome is the compatibility boundary between older
        Workflow code and the new canonical AgentResult contract.

        AgentResult itself remains strict and still requires:
            status
            agent
            task_id
        """

        payload = dict(result)

        payload.setdefault(
            "agent",
            "unknown",
        )

        payload.setdefault(
            "task_id",
            "unknown",
        )

        return AgentResult.from_dict(
            payload
        )

    # ----------------------------------------------------------------
    # Factory methods
    # ----------------------------------------------------------------

    @classmethod
    def success(
        cls,
        stage: WorkflowStage,
        result: AgentResult,
    ) -> "StageOutcome":
        """
        Create a successful StageOutcome.
        """

        if not isinstance(result, AgentResult):
            raise TypeError(
                "StageOutcome.success requires an AgentResult"
            )

        return cls(
            stage=stage,
            status=result.status,
            result=result,
            exception=None,
        )

    @classmethod
    def failure(
        cls,
        stage: WorkflowStage,
        exception: Exception,
    ) -> "StageOutcome":
        """
        Create a failed StageOutcome.
        """

        if not isinstance(exception, Exception):
            raise TypeError(
                "StageOutcome.failure requires an Exception"
            )

        return cls(
            stage=stage,
            status="failed",
            result=None,
            exception=exception,
        )

    # ----------------------------------------------------------------
    # Compatibility representation
    # ----------------------------------------------------------------

    @property
    def result_dict(self) -> dict[str, Any]:
        """
        Return the canonical dictionary representation of result.

        ``result`` remains the canonical AgentResult object.

        This property exists for Workflow code and legacy callers
        that still consume dictionary-shaped results.
        """

        if self.result is None:
            return {}

        return self.result.to_dict()

    # ----------------------------------------------------------------
    # Convenience helpers
    # ----------------------------------------------------------------

    @property
    def succeeded(self) -> bool:
        """
        Whether this stage completed without an exception.
        """

        return (
            self.exception is None
            and self.result is not None
            and self.status != "failed"
        )

    @property
    def failed(self) -> bool:
        """
        Whether this stage failed.
        """

        return (
            self.status == "failed"
            or self.exception is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert StageOutcome into a serializable dictionary.
        """

        return {
            "stage": self.stage.value,
            "status": self.status,
            "result": self.result_dict,
            "exception": (
                str(self.exception)
                if self.exception is not None
                else None
            ),
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
        tester = None
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
            # if task.status == "pending":
            #     self.task_manager.mark_ready(task_id)

            # if task.status not in {"ready", "running"}:
            #     raise ValueError(
            #         f"Task {task_id} is not ready or running: {task.status}"
            #     )

            if task.status == "ready":
                self.task_manager.mark_running(task_id)

            self._build_context(task)
            # ------------------------------------------------------------
            # 1. Developer
            # ------------------------------------------------------------
            developer_outcome = self._run_developer(
                task
            )
            
            self._apply_developer_outcome(
                task,
                developer_outcome,
            )
            
            if task.status == "failed":
                return task

            # ------------------------------------------------------------
            # 2. Tester quality gate
            #
            # New workflow:
            #     Developer -> Tester -> Reviewer
            #
            # Legacy workflow:
            #     Developer -> Reviewer
            #
            # When tester is None, skip the Tester quality gate entirely.
            # ------------------------------------------------------------
            if self.tester is not None:
                tester_outcome = self._run_tester(
                    task
                )

                if not self._handle_tester_result(
                    task,
                    tester_outcome,
                ):
                    if task.status == "failed":
                        return task

                    if tester_outcome.status != "passed":
                        continue

            # ------------------------------------------------------------
            # 3. Reviewer
            #
            # If Tester exists:
            #     Reviewer is reached only when Tester returns "passed".
            #
            # If Tester does not exist:
            #     Developer goes directly to Reviewer.
            # ------------------------------------------------------------
            self.task_manager.mark_reviewing(
                task.id
            )

            review_outcome = self._run_reviewer(
                task
            )

            review_action = self._apply_reviewer_outcome(
                task,
                review_outcome,
            )

            if review_action == "completed":
                return task

            if review_action == "failed":
                return task

            if review_action == "revision":
                continue

        return task


    def _run_tester(
        self,
        task: Task,
    ) -> StageOutcome:
        """
        Execute the tester stage and always return a StageOutcome.
        """

        try:
            raw_result = self.tester.run(task)

            result = normalize_agent_result(
                raw_result
            )

            return StageOutcome.success(
                WorkflowStage.TESTER,
                result,
            )

        except Exception as exc:
            return StageOutcome.failure(
                WorkflowStage.TESTER,
                exc,
            )
    
    
    def _apply_tester_outcome(
        self,
        task: Task,
        outcome: StageOutcome,
    ) -> None:

        # ------------------------------------------------------------
        # 1. Tester passed
        #
        # 正常质量门禁通过：
        #
        #     Developer -> Tester -> Reviewer
        # ------------------------------------------------------------
        if outcome.status == "passed":
            self.task_manager.record_test_result(
                task.id,
                outcome.result_dict,
            )

            self.task_manager.set_feedback(
                task.id,
                "tester",
                outcome.result,
            )

            return

        # ------------------------------------------------------------
        # 2. Tester execution exception
        #
        # 这是 Agent 执行失败，而不是测试发现代码问题。
        #
        # 例如：
        #
        #     tester.run()
        #         ↓
        #     RuntimeError
        #
        # 必须进入 FAILED，而不是 Developer revision。
        # ------------------------------------------------------------
        if outcome.exception is not None:
            self.task_manager.record_test_result(
                task.id,
                outcome.result_dict,
            )

            self.task_manager.mark_failed(
                task.id,
                outcome.result_dict.get(
                    "message",
                    "Tester execution failed",
                ),
            )

            return

        # ------------------------------------------------------------
        # 3. Tester returned "failed"
        #
        # 这是正常的 Quality Gate failure。
        #
        # 含义：
        #
        #     测试发现代码问题
        #         ↓
        #     Developer revision
        #
        # 不能把 task 标记成 FAILED。
        # ------------------------------------------------------------
        if outcome.status == "failed":
            self.task_manager.mark_tester_revision_required(
                task.id,
                outcome.result_dict,
            )

            return

        # ------------------------------------------------------------
        # 4. Unknown / invalid Tester status
        #
        # 例如：
        #
        #     status == "invalid"
        #     status == "unknown"
        #     status == "foo"
        #
        # 这不是正常 Quality Gate failure。
        #
        # 属于 AgentResult contract violation。
        # ------------------------------------------------------------
        self.task_manager.mark_failed(
            task.id,
            (
                "Invalid tester result status: "
                f"{outcome.status}"
            ),
        )
    
    
    def _handle_tester_result(
        self,
        task: Task,
        outcome: StageOutcome,
    ) -> bool:

        self._apply_tester_outcome(
            task,
            outcome,
        )

        return outcome.status == "passed"

    def _run_developer(
        self,
        task: Task,
    ) -> StageOutcome:
        """
        Execute the developer stage and always return a StageOutcome.

        The method itself does not mutate task state on failure.
        Task state transitions are handled centrally by
        _apply_developer_outcome().
        """

        try:
            raw_result = self.developer.run(task)

            result = normalize_agent_result(
                raw_result
            )

            return StageOutcome.success(
                WorkflowStage.DEVELOPER,
                result,
            )

        except Exception as exc:
            return StageOutcome.failure(
                WorkflowStage.DEVELOPER,
                exc,
            )
        
    def _apply_developer_outcome(
        self,
        task: Task,
        outcome: StageOutcome,
    ) -> None:

        if outcome.exception is not None:
            error = (
                f"Developer execution failed: "
                f"{outcome.exception}"
            )

            self.task_manager.mark_failed(
                task.id,
                error,
            )

            raise outcome.exception

        if outcome.status == "completed":
            self.task_manager.mark_developer_completed(
                task.id,
                outcome.result_dict,
            )
            return

        message = (
            outcome.result.message
            if outcome.result is not None
            else "Developer execution failed"
        )

        self.task_manager.mark_failed(
            task.id,
            message,
        )
    
    
    def _run_reviewer(
        self,
        task: Task,
    ) -> StageOutcome:
        """
        Execute the reviewer stage and always return a StageOutcome.
        """

        try:
            raw_result = self.reviewer.run(task)

            result = normalize_agent_result(
                raw_result
            )

            return StageOutcome.success(
                WorkflowStage.REVIEWER,
                result,
            )

        except Exception as exc:
            return StageOutcome.failure(
                WorkflowStage.REVIEWER,
                exc,
            )
    
    def _apply_reviewer_outcome(
        self,
        task: Task,
        outcome: StageOutcome,
    ) -> str:

        if task.status == TaskStatus.REVIEW_PENDING.value:
            self.task_manager.mark_reviewing(task.id)

        if outcome.exception is not None:
            error = (
                f"Reviewer execution failed: "
                f"{outcome.exception}"
            )

            self.task_manager.mark_failed(
                task.id,
                error,
            )

            raise outcome.exception

        if outcome.status == "approved":
            self.task_manager.mark_review_approved(
                task.id,
                outcome.result_dict,
            )

            return "completed"

        if outcome.status == "revision":
            self.task_manager.mark_review_revision_required(
                task.id,
                outcome.result_dict,
            )

            if task.review_round >= self.max_review_rounds:
                self.task_manager.mark_failed(
                    task.id,
                    (
                        f"Task failed review after "
                        f"{self.max_review_rounds} rounds"
                    ),
                )

                return "failed"

            return "revision"

        if outcome.status == "failed":
            message = (
                outcome.result.message
                if outcome.result is not None
                else "Reviewer execution failed"
            )

            self.task_manager.mark_failed(
                task.id,
                message,
            )

            return "failed"

        self.task_manager.mark_failed(
            task.id,
            (
                "Unknown reviewer status: "
                f"{outcome.status}"
            ),
        )

        return "failed"
    
 
    
    def _handle_review_result(
        self,
        task: Task,
        outcome: StageOutcome,
    ) -> str:

        if outcome.status == "approved":
            return "completed"

        if outcome.status == "failed":
            return "failed"

        if outcome.status == "revision":
            if task.review_round >= self.max_review_rounds:
                self.task_manager.mark_failed(
                    task.id,
                    f"Task failed review after "
                    f"{self.max_review_rounds} rounds",
                )
                return "failed"

            return "revision"

        self.task_manager.mark_failed(
            task.id,
            f"Unknown review status: "
            f"{outcome.status}",
        )

        return "failed"
    
    
    def _build_context(self, task: Task) -> None:
        """Build and persist dependency context for the current task."""

        all_tasks = {
            item.id: item
            for item in self.task_manager.get_all_tasks()
        }

        dependency_context = build_task_context(
            task,
            all_tasks,
        )

        task.context["dependencies"] = dependency_context