from typing import Any

from runtime.task import Task
from runtime.task_status import (
    TaskStatus,
    validate_transition,
)

class TaskManager:
    """Own task state transitions and task lifecycle data."""

    def __init__(self, tasks: list[Task]):
        self.tasks = {task.id: task for task in tasks}
        
    def transition(
        self,
        task_id: str,
        target_status: str | TaskStatus,
    ) -> Task:
        """
        Transition a task to a new lifecycle state.

        All Task status mutations must go through this method.
        """
        task = self.get_task(task_id)

        validate_transition(
            task.status,
            target_status,
        )

        new_status = (
            target_status.value
            if isinstance(target_status, TaskStatus)
            else target_status
        )
        task.status_history.append({
            "from": task.status,
            "to": new_status,
        })

        task.status = new_status

        return task

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
                self.transition(
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
                self.transition(
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
                self.transition(
                    task.id,
                    TaskStatus.READY,
                )
                ready.append(task)

        return ready

    def mark_ready(self, task_id: str) -> None:
        self.transition(
            task_id,
            TaskStatus.READY,
        )

        self.record_error(
            task_id,
            None,
        )

    def mark_running(self, task_id: str) -> None:
        self.transition(
            task_id,
            TaskStatus.RUNNING,
        )

        self.record_error(
            task_id,
            None,
        )

    def mark_developer_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> None:
        task = self.transition(
            task_id,
            TaskStatus.REVIEW_PENDING,
        )

        self.record_error(
            task_id,
            None,
        )

        if result is not None:
            self.record_result(
                task_id,
                result,
            )

    def mark_review_pending(
        self,
        task_id: str,
        result: dict | None = None,
    ) -> None:
        self.mark_developer_completed(task_id, result)

    def mark_reviewing(self, task_id: str) -> None:
        self.transition(
            task_id,
            TaskStatus.REVIEWING,
        )

    def mark_review_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
    ) -> None:
        task = self.transition(
            task_id,
            TaskStatus.RUNNING,
        )

        if review_result is not None:
            if not isinstance(review_result, dict):
                raise TypeError("review_result must be a dict")

            self.record_review_result(
                task.id,
                review_result,
            )
            self.set_feedback(
                task.id,
                "reviewer",
                review_result,
            )

        self.record_error(
            task.id,
            None,
        )

    def mark_review_approved(
        self,
        task_id: str,
        review_result: dict,
    ) -> None:
        if not isinstance(review_result, dict):
            raise TypeError(
                "review_result must be a dict"
            )

        task = self.transition(
            task_id,
            TaskStatus.COMPLETED,
        )

        self.record_review_result(
            task_id,
            review_result,
        )

        self.record_error(
            task_id,
            None,
        )

    def mark_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> None:
        task = self.transition(
            task_id,
            TaskStatus.COMPLETED,
        )

        self.record_error(
            task_id,
            None,
        )

        if result is not None:
            self.record_result(
                task_id,
                result,
            )

    # Backward-compatible API. New workflow code uses the explicit review methods.
    # Legacy compatibility API.
    def mark_revision(self, task_id: str, review: dict) -> None:
        task = self.get_task(task_id)
        if task.status != "reviewing":
            raise ValueError(f"Task {task_id} is not reviewing")
        self.mark_review_revision_required(task_id, review)

    # Legacy compatibility API.
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
                    raise TypeError(
                        "review_result must be a dict"
                    )

                self.record_review_result(
                    task_id,
                    review_result,
                )

                self.set_feedback(
                    task_id,
                    "reviewer",
                    review_result,
                )

            self.transition(
                task_id,
                TaskStatus.PENDING,
            )

            self.record_error(
                task_id,
                error,
            )
        else:
            raise ValueError(
                f"Task {task_id} cannot require revision from status {task.status}"
            )

    # Legacy compatibility API.
    # The current workflow uses:
    #
    #     reviewing -> running
    #
    # for Reviewer revision, so new workflow code should not call this method.
    def retry_revision(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status != "revision":
            raise ValueError(f"Task {task_id} is not in revision")
        # task.status = "ready"
        self.transition(
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
        if not isinstance(test_result, dict):
            raise TypeError(
                "test_result must be a dict"
            )

        self.transition(
            task_id,
            TaskStatus.RUNNING,
        )

        self.record_test_result(
            task_id,
            test_result,
        )

        self.set_feedback(
            task_id,
            "tester",
            test_result,
        )

        self.record_error(
            task_id,
            None,
        )

    def ensure_executable(self, task_id: str) -> Task:
        """Validate that a task can enter workflow execution."""
        task = self.get_task(task_id)

        if task.status == "pending":
            self.get_ready_tasks()

        task = self.get_task(task_id)

        if task.status not in {
            "ready",
            "running",
        }:
            raise ValueError(
                f"Task {task_id} is not executable from status "
                f"{task.status}"
            )

        return task
    
    def is_terminal(self, task_id: str) -> bool:
        task = self.get_task(task_id)

        return task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.BLOCKED.value,
        }
        
    
    def is_active(self, task_id: str) -> bool:
        task = self.get_task(task_id)

        return task.status in {
            TaskStatus.READY.value,
            TaskStatus.RUNNING.value,
            TaskStatus.REVIEW_PENDING.value,
            TaskStatus.REVIEWING.value,
            TaskStatus.REVISION.value,
        }
        
    def record_test_result(
        self,
        task_id: str,
        test_result: dict,
    ) -> Task:
        """
        Record the latest tester result and append it to test history.

        Re-recording the same result is idempotent and does not
        create a duplicate history entry.
        """
        if not isinstance(test_result, dict):
            raise TypeError(
                "test_result must be a dict"
            )

        task = self.get_task(task_id)

        task.test_result = test_result

        if not task.test_history or task.test_history[-1] != test_result:
            task.test_history.append(test_result)

        return task
    
    def record_review_result(
        self,
        task_id: str,
        review_result: dict,
        *,
        increment_round: bool = True,
    ) -> Task:
        if not isinstance(review_result, dict):
            raise TypeError(
                "review_result must be a dict"
            )

        task = self.get_task(task_id)

        task.review_result = review_result
        task.review_history.append(review_result)

        if increment_round:
            task.review_round += 1

        return task
    
    def set_feedback(
        self,
        task_id: str,
        source: str,
        feedback: dict | str,
    ) -> Task:
        task = self.get_task(task_id)

        if not isinstance(source, str) or not source:
            raise ValueError(
                "feedback source must be a non-empty string"
            )

        task.context[f"{source}_feedback"] = feedback

        return task
    
    def record_result(
        self,
        task_id: str,
        result: dict | Any,
    ) -> Task:
        task = self.get_task(task_id)

        if hasattr(result, "to_dict"):
            result = result.to_dict()

        if not isinstance(result, dict):
            raise TypeError(
                "result must be a dict or support to_dict()"
            )

        task.result = result

        return task
    
    def record_error(
        self,
        task_id: str,
        error: str | None,
    ) -> Task:
        if error is not None and not isinstance(error, str):
            raise TypeError(
                "error must be a string or None"
            )

        task = self.get_task(task_id)

        task.error = error

        return task
    
    
    def mark_failed(
        self,
        task_id: str,
        error: str,
    ) -> None:
        task = self.get_task(task_id)

        if task.status not in {
            TaskStatus.RUNNING.value,
            TaskStatus.REVIEWING.value,
            TaskStatus.REVIEW_PENDING.value,
        }:
            raise ValueError(
                f"Task {task_id} cannot be failed "
                f"from status {task.status}"
            )

        self.transition(
            task_id,
            TaskStatus.FAILED,
        )

        self.record_error(
            task_id,
            error,
        )