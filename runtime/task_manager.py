from runtime.task import Task


VALID_STATUSES = {
    "pending",
    "ready",
    "running",
    "review_pending",
    "reviewing",
    "revision",
    "completed",
    "failed",
    "blocked",
}


class TaskManager:
    """Own task state transitions and task lifecycle data."""

    def __init__(self, tasks: list[Task]):
        self.tasks = {task.id: task for task in tasks}

    def get_task(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def get_all_tasks(self) -> list[Task]:
        return list(self.tasks.values())

    def get_ready_tasks(self) -> list[Task]:
        """Promote pending tasks whose dependencies are satisfied."""
        ready = []

        for task in self.tasks.values():
            if task.status != "pending":
                continue

            missing_dependencies = [
                dependency_id
                for dependency_id in task.dependencies
                if dependency_id not in self.tasks
            ]

            if missing_dependencies:
                task.status = "blocked"
                task.error = (
                    "Missing dependencies: "
                    + ", ".join(missing_dependencies)
                )
                continue

            failed_dependencies = [
                dependency_id
                for dependency_id in task.dependencies
                if self.tasks[dependency_id].status in {"failed", "blocked"}
            ]

            if failed_dependencies:
                task.status = "blocked"
                task.error = (
                    "Blocked by dependencies: "
                    + ", ".join(failed_dependencies)
                )
                continue

            if all(
                self.tasks[dependency_id].status == "completed"
                for dependency_id in task.dependencies
            ):
                task.status = "ready"
                ready.append(task)

        return ready

    def mark_ready(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != "pending":
            raise ValueError(
                f"Task {task_id} cannot become ready from status {task.status}"
            )
        task.status = "ready"
        task.error = None

    def mark_running(self, task_id: str) -> None:
        """ready -> running."""
        task = self.get_task(task_id)
        if task.status != "ready":
            raise ValueError(f"Task {task_id} is not ready")
        task.status = "running"
        task.error = None

    def mark_developer_completed(
        self,
        task_id: str,
        result: dict | None = None,
    ) -> None:
        """running -> review_pending; Developer completion is not task completion."""
        task = self.get_task(task_id)
        if task.status != "running":
            raise ValueError(f"Task {task_id} is not running")

        task.status = "review_pending"
        task.error = None
        if result is not None:
            task.result = result

    def mark_review_pending(
        self,
        task_id: str,
        result: dict | None = None,
    ) -> None:
        self.mark_developer_completed(task_id, result)

    def mark_reviewing(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != "review_pending":
            raise ValueError(f"Task {task_id} is not review_pending")
        task.status = "reviewing"

    def mark_review_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
    ) -> None:
        """reviewing -> running and preserve feedback for the next Developer round."""
        task = self.get_task(task_id)
        if task.status != "reviewing":
            raise ValueError(f"Task {task_id} is not reviewing")

        if review_result is not None and not isinstance(review_result, dict):
            raise TypeError("review_result must be a dict")

        if review_result is not None:
            task.review_result = review_result
            task.result["review"] = review_result
            task.review_history.append(review_result)
            task.review_round += 1
            task.context["reviewer_feedback"] = review_result

        task.status = "running"
        task.error = None

    def mark_review_approved(
        self,
        task_id: str,
        review_result: dict,
    ) -> None:
        """reviewing -> completed."""
        task = self.get_task(task_id)
        if task.status != "reviewing":
            raise ValueError(f"Task {task_id} is not reviewing")

        if not isinstance(review_result, dict):
            raise TypeError("review_result must be a dict")

        task.review_result = review_result
        task.result["review"] = review_result
        task.review_history.append(review_result)
        task.review_round += 1
        task.status = "completed"
        task.error = None

    def mark_completed(
        self,
        task_id: str,
        result: dict | None = None,
    ) -> None:
        """Complete a non-review workflow task."""
        task = self.get_task(task_id)
        if task.status != "running":
            raise ValueError(f"Task {task_id} is not running")

        task.status = "completed"
        task.error = None
        if result is not None:
            task.result = result

    def mark_failed(self, task_id: str, error: str) -> None:
        """Fail a task from any active execution state."""
        task = self.get_task(task_id)
        if task.status not in {"running", "reviewing", "review_pending"}:
            raise ValueError(
                f"Task {task_id} cannot be failed from status {task.status}"
            )
        task.status = "failed"
        task.error = error

    # Backward-compatible API. New workflow code uses the explicit review methods.
    def mark_revision(self, task_id: str, review: dict) -> None:
        task = self.get_task(task_id)
        if task.status != "reviewing":
            raise ValueError(f"Task {task_id} is not reviewing")
        self.mark_review_revision_required(task_id, review)

    def mark_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Legacy compatibility wrapper; prefer mark_review_revision_required."""
        task = self.get_task(task_id)
        if task.status == "reviewing":
            self.mark_review_revision_required(task_id, review_result)
        elif task.status == "completed":
            if review_result is not None:
                if not isinstance(review_result, dict):
                    raise TypeError("review_result must be a dict")
                task.review_result = review_result
                task.result["review"] = review_result
                task.review_history.append(review_result)
                task.context["reviewer_feedback"] = review_result
            task.status = "pending"
            task.error = error
        else:
            raise ValueError(
                f"Task {task_id} cannot require revision from status {task.status}"
            )

    def retry_revision(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != "revision":
            raise ValueError(f"Task {task_id} is not in revision")
        task.status = "ready"
        task.error = None

    def apply_review_result(self, task_id: str, review_result: dict) -> str:
        if not isinstance(review_result, dict):
            raise TypeError("review_result must be a dict")

        status = review_result.get("status")
        if status == "approved":
            self.mark_review_approved(task_id, review_result)
            return "completed"
        if status == "revision":
            self.mark_review_revision_required(task_id, review_result)
            return "running"
        raise ValueError(f"Unknown reviewer status: {status}")

    def get_blocked_tasks(self) -> list[Task]:
        return [task for task in self.tasks.values() if task.status == "blocked"]

    def get_failed_tasks(self) -> list[Task]:
        return [task for task in self.tasks.values() if task.status == "failed"]

    def has_failed_tasks(self) -> bool:
        return any(
            task.status in {"failed", "blocked"}
            for task in self.tasks.values()
        )

    def is_finished(self) -> bool:
        return all(task.status == "completed" for task in self.tasks.values())
