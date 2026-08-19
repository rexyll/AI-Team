from typing import Any

from runtime.task import Task
from runtime.task_status import (
    TaskStatus,
    validate_transition,
)

# VALID_STATUSES = {
#     "pending",
#     "ready",
#     "running",
#     "review_pending",
#     "reviewing",
#     "revision",
#     "completed",
#     "failed",
#     "blocked",
# }


class TaskManager:
    """Own task state transitions and task lifecycle data."""

    def __init__(self, tasks: list[Task]):
        self.tasks = {task.id: task for task in tasks}
        
    def _transition(
        self,
        task_id: str,
        target_status: str | TaskStatus,
    ) -> None:
        task = self.get_task(task_id)

        validate_transition(
            task.status,
            target_status,
        )

        task.status = (
            target_status.value
            if isinstance(target_status, TaskStatus)
            else target_status
        )

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
                # task.status = "blocked"
                self._transition(
                    task.id,
                    TaskStatus.BLOCKED,
                )
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
                # task.status = "blocked"
                self._transition(
                    task.id,
                    TaskStatus.BLOCKED,
                )
                task.error = (
                    "Blocked by dependencies: "
                    + ", ".join(failed_dependencies)
                )
                continue

            if all(
                self.tasks[dependency_id].status == "completed"
                for dependency_id in task.dependencies
            ):
                self._transition(
                    task.id,
                    TaskStatus.READY,
                )
                ready.append(task)

        return ready

    def mark_ready(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != "pending":
            raise ValueError(
                f"Task {task_id} cannot become ready from status {task.status}"
            )
        # task.status = "ready"
        self._transition(
            task.id,
            TaskStatus.READY,
        )
        task.error = None

    def mark_running(self, task_id: str) -> None:
        task = self.get_task(task_id)

        self._transition(
            task_id,
            TaskStatus.RUNNING,
        )

        task.error = None

    def mark_developer_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> None:
        """running -> review_pending; Developer completion is not task completion."""
        task = self.get_task(task_id)

        if task.status != "running":
            raise ValueError(
                f"Task {task_id} is not running"
            )

        self._transition(
            task_id,
            TaskStatus.REVIEW_PENDING,
        )

        task.error = None

        if result is not None:
            if hasattr(result, "to_dict"):
                result = result.to_dict()

            if not isinstance(result, dict):
                raise TypeError(
                    "Developer result must be a dict or support to_dict()"
                )

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
        self._transition(
            task_id,
            TaskStatus.REVIEWING,
        )

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
            task.review_history.append(review_result)
            task.review_round += 1
            task.context["reviewer_feedback"] = review_result

        self._transition(
            task.id,
            TaskStatus.RUNNING,
        )
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
        task.review_history.append(review_result)
        task.review_round += 1
        self._transition(
            task_id,
            TaskStatus.COMPLETED,
        )
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

        # task.status = "completed"
        self._transition(
            task.id,
            TaskStatus.COMPLETED,
        )
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
        self._transition(
            task_id,
            TaskStatus.FAILED,
        )
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
                task.review_history.append(review_result)
                task.context["reviewer_feedback"] = review_result
            # task.status = "pending"
            self._transition(
                task.id,
                TaskStatus.PENDING,
            )
            task.error = error
        else:
            raise ValueError(
                f"Task {task_id} cannot require revision from status {task.status}"
            )

    def retry_revision(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != "revision":
            raise ValueError(f"Task {task_id} is not in revision")
        # task.status = "ready"
        self._transition(
            task.id,
            TaskStatus.READY,
        )
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
        
    def mark_tester_revision_required(
        self,
        task_id: str,
        test_result: dict,
    ) -> None:
        """
        Tester failed -> send task back to Developer.

        State transition:

            review_pending -> running

        Tester feedback is preserved so the next Developer round can
        inspect the failure reason through task.context["tester_feedback"].
        """
        task = self.get_task(task_id)

        if task.status != "review_pending":
            raise ValueError(
                f"Task {task_id} is not review_pending"
            )

        if not isinstance(test_result, dict):
            raise TypeError(
                "test_result must be a dict"
            )

       # 保存本次 Tester 结果。
        #
        # test_history 已经由 TaskWorkflow._run_tester() 统一记录，
        # 这里不能再次 append，否则一次 Tester 执行会产生两条历史记录。
        task.test_result = test_result

        # 将 Tester 的失败反馈传递给下一轮 Developer。
        task.context["tester_feedback"] = test_result

        # Tester 失败是可恢复错误：
        #
        #   Developer
        #       ↓
        #   Tester FAILED
        #       ↓
        #   Developer revision
        #
        # 因此直接回到 RUNNING，让 workflow 下一轮重新执行 Developer。
        self._transition(
            task_id,
            TaskStatus.RUNNING,
        )

        # 清除之前可能存在的错误状态
        task.error = None
