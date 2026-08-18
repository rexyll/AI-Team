from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter


MAX_REVIEW_ROUNDS = 3


class TaskWorkflow:
    """Execute one task through Developer/Reviewer iterations."""

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
