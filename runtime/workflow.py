from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.result_normalizer import normalize_agent_result

MAX_REVIEW_ROUNDS = 3


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
        task = self.task_manager.get_task(task_id)

        for _ in range(self.max_review_rounds):
            if task.status == "pending":
                self.task_manager.get_ready_tasks()

            if task.status not in {"ready", "running"}:
                raise ValueError(
                    f"Task {task_id} is not ready or running: {task.status}"
                )

            if task.status == "ready":
                self.task_manager.mark_running(task_id)

            # ------------------------------------------------------------
            # 1. Developer
            # ------------------------------------------------------------
            self._run_developer(task)

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
                tester_passed = self._run_tester(task)

                if not self._handle_tester_result(
                    task,
                    tester_passed,
                ):
                    if task.status == "failed":
                        return task

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
            review_status = self._run_reviewer(task)

            result = self._handle_review_result(
                task,
                review_status,
            )

            if result == "completed":
                return task

            if result == "failed":
                return task

            # revision
            continue

        return task

    def _run_tester(self, task: Task) -> bool:
        """Run Tester and enforce the Tester quality gate.

        Returns True only for an explicit ``passed`` result.

        A legitimate ``failed`` result is recoverable and handled by
        execute() as a Developer revision.

        Exceptions and malformed results are terminal workflow failures.
        """
        try:
            raw_result = self.tester.run(task)
            result = normalize_agent_result(raw_result)

        except Exception as exc:
            self.task_manager.mark_failed(
                task.id,
                f"Tester failed: {type(exc).__name__}: {exc}",
            )
            raise

        
        status = result.status

        if status not in {"passed", "failed"}:
            self.task_manager.mark_failed(
                task.id,
                f"Tester returned invalid status: {status}",
            )
            return False
        result_dict = result.to_dict()
        
        task.test_result = result_dict
        task.test_history.append(result_dict)
        task.context["tester_feedback"] = result_dict

        return status == "passed"
    
    def _handle_tester_result(
        self,
        task: Task,
        tester_passed: bool,
    ) -> bool:
        """Handle Tester result.

        Returns:
            True when workflow should continue to Reviewer.
            False when Developer must be executed again.
        """
        if tester_passed:
            return True

        if task.status == "failed":
            return False

        self.task_manager.mark_tester_revision_required(
            task.id,
            task.test_result,
        )

        return False

    def _normalize_developer_result(
        self,
        result,
        task: Task,
    ):
        if isinstance(result, dict):
            result = dict(result)

            result.setdefault(
                "agent",
                "developer",
            )

            result.setdefault(
                "task_id",
                task.id,
            )

        return normalize_agent_result(result)

    def _run_developer(self, task: Task) -> bool:
        """Run Developer and persist the implementation result.

        Returns:
            True when Developer completed successfully.

        Raises:
            Exception:
                Re-raises the original Developer exception after marking
                the task as failed.
        """
        try:
            raw_result = self.developer.run(task)

            developer_result = self._normalize_developer_result(
                raw_result,
                task,
            )

            self.task_manager.mark_developer_completed(
                task.id,
                developer_result,
            )

            return True

        except Exception as exc:
            self.task_manager.mark_failed(
                task.id,
                f"Developer execution failed: "
                f"{type(exc).__name__}: {exc}",
            )
            raise
        
    def _run_reviewer(self, task: Task) -> str:
        """Run Reviewer and return the review decision.

        Returns:
            ``approved`` or ``revision``.

        Raises:
            Exception:
                Re-raises Reviewer execution failures.
        """
        self.task_manager.mark_reviewing(task.id)

        try:
            raw_result = self.reviewer.run(task)
            review_result = normalize_agent_result(raw_result)

        except Exception as exc:
            self.task_manager.mark_failed(
                task.id,
                f"Reviewer execution failed: "
                f"{type(exc).__name__}: {exc}",
            )
            raise

        review_status = review_result.status
        review_data = review_result.to_dict()

        if review_status == "approved":
            self.task_manager.mark_review_approved(
                task.id,
                review_data,
            )
            return "approved"

        if review_status == "revision":
            self.task_manager.mark_review_revision_required(
                task.id,
                review_data,
            )
            return "revision"

        self.task_manager.mark_failed(
            task.id,
            f"Unknown reviewer status: {review_status}",
        )

        return "failed"
    
    def _handle_review_result(
        self,
        task: Task,
        review_status: str,
    ) -> str:
        """Handle Reviewer result.

        Returns:
            ``completed``:
                Workflow finished successfully.

            ``failed``:
                Workflow finished with failure.

            ``revision``:
                Developer must execute another round.
        """
        if review_status == "approved":
            return "completed"

        if review_status == "failed":
            return "failed"

        if review_status == "revision":
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
            f"Unknown review status: {review_status}",
        )

        return "failed"