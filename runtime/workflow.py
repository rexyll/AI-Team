from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter


MAX_REVIEW_ROUNDS = 3


class TaskWorkflow:
    """Execute one task through Developer/Tester/Reviewer iterations."""

    def __init__(
        self,
        task_manager: TaskManager,
        developer,
        tester,
        reviewer,
        agent_router: AgentRouter,
        max_review_rounds: int = MAX_REVIEW_ROUNDS,
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
            try:
                developer_result = self.developer.run(task)
                self.task_manager.mark_developer_completed(
                    task_id,
                    developer_result,
                )
            except Exception as exc:
                self.task_manager.mark_failed(
                    task_id,
                    f"Developer execution failed: {type(exc).__name__}: {exc}",
                )
                raise

            # ------------------------------------------------------------
            # 2. Tester quality gate
            #
            # Reviewer MUST NOT run unless Tester explicitly returns
            # status == "passed".
            # ------------------------------------------------------------
            tester_passed = self._run_tester(task)

            if not tester_passed:
                # Invalid tester results and tester exceptions are terminal
                # failures. _run_tester has already marked the task failed.
                if task.status == "failed":
                    return task

                # A legitimate TEST_FAILED result is a revision request.
                # Preserve the tester feedback and send the task back to the
                # Developer. Do not enter Reviewer.
                task.context["tester_feedback"] = task.test_result
                task.status = "running"
                task.error = None
                continue

            # ------------------------------------------------------------
            # 3. Reviewer
            # ------------------------------------------------------------
            self.task_manager.mark_reviewing(task_id)

            try:
                review_result = self.reviewer.run(task)
            except Exception as exc:
                self.task_manager.mark_failed(
                    task_id,
                    f"Reviewer execution failed: {type(exc).__name__}: {exc}",
                )
                raise

            if not isinstance(review_result, dict):
                self.task_manager.mark_failed(
                    task_id,
                    "Reviewer returned a non-dict result",
                )
                return task

            review_status = review_result.get("status")

            if review_status == "approved":
                self.task_manager.mark_review_approved(
                    task_id,
                    review_result,
                )
                return task

            if review_status == "revision":
                self.task_manager.mark_review_revision_required(
                    task_id,
                    review_result,
                )

                if task.review_round >= self.max_review_rounds:
                    self.task_manager.mark_failed(
                        task_id,
                        f"Task failed review after {self.max_review_rounds} rounds",
                    )
                    return task

                continue

            self.task_manager.mark_failed(
                task_id,
                f"Unknown reviewer status: {review_status}",
            )
            return task

        if task.status != "completed":
            self.task_manager.mark_failed(
                task_id,
                "Task workflow ended without successful review",
            )

        return task

    def _run_tester(self, task: Task) -> bool:
        """Run Tester and enforce the Tester quality gate.

        Returns True only for an explicit ``passed`` result. A legitimate
        ``failed`` result is recoverable and is handled by execute() as a
        Developer revision. Exceptions and malformed results are terminal
        workflow failures.
        """
        try:
            result = self.tester.run(task)
        except Exception as exc:
            task.status = "failed"
            task.error = f"Tester failed: {type(exc).__name__}: {exc}"
            raise

        if not isinstance(result, dict):
            task.status = "failed"
            task.error = "Tester returned invalid result type"
            return False

        status = result.get("status")

        if status not in {"passed", "failed"}:
            task.status = "failed"
            task.error = f"Tester returned invalid status: {status}"
            return False

        task.test_result = result
        task.test_history.append(result)
        task.context["tester_feedback"] = result

        return status == "passed"
