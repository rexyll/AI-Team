from threading import RLock
from typing import Any

from runtime.task import Task
from runtime.task_status import (
    TaskStatus,
    can_transition,
    validate_transition,
)


class ResultPayload(dict):
    """
    Canonical result dictionary with backward-compatible access.

    Canonical storage remains exactly the same as AgentResult.to_dict().
    Legacy callers may still access business fields directly; those
    fields are resolved from ``data`` and are not stored as extra keys.
    """

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            data = super().get("data")
            if isinstance(data, dict) and key in data:
                return data[key]
            raise

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        if super().__contains__(key):
            return True
        data = super().get("data")
        return isinstance(data, dict) and key in data


class TaskManager:
    """
    Central owner of Task lifecycle state and task execution data.

    Workflow decides WHAT happened. TaskManager decides WHETHER the
    corresponding state transition is legal and persists the result.

    TaskManager is also the synchronization boundary for shared Task
    lifecycle state. Worker threads may execute independently, but every
    lifecycle mutation and state query is protected by one re-entrant lock.
    The lock never covers agent/tool execution itself.
    """

    def __init__(self, tasks: list[Task]):
        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")

        self.tasks: dict[str, Task] = {}
        self._lock = RLock()

        for task in tasks:
            if not isinstance(task, Task):
                raise TypeError("all tasks must be Task instances")
            if task.id in self.tasks:
                raise ValueError(f"Duplicate task id: {task.id}")
            self.tasks[task.id] = task

    # ------------------------------------------------------------------
    # Basic task access
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Task:
        with self._lock:
            try:
                return self.tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"Unknown task id: {task_id}") from exc

    def get_all_tasks(self) -> list[Task]:
        with self._lock:
            return list(self.tasks.values())

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    @staticmethod
    def can_transition(
        current: str | TaskStatus,
        target: str | TaskStatus,
    ) -> bool:
        return can_transition(current, target)

    def transition(
        self,
        task_id: str,
        target_status: str | TaskStatus,
    ) -> Task:
        """
        Validate and commit one lifecycle transition atomically.

        Validation, history append, and status assignment are one critical
        section, so concurrent workers cannot both commit the same source
        state transition.
        """
        with self._lock:
            task = self.get_task(task_id)
            current_status = task.status

            validate_transition(current_status, target_status)

            new_status = (
                target_status.value
                if isinstance(target_status, TaskStatus)
                else target_status
            )

            task.status_history.append(
                {"from": current_status, "to": new_status}
            )
            task.status = new_status
            return task

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_terminal(self, task_id: str) -> bool:
        with self._lock:
            task = self.get_task(task_id)
            return task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.BLOCKED.value,
            }

    def is_active(self, task_id: str) -> bool:
        with self._lock:
            task = self.get_task(task_id)
            return task.status in {
                TaskStatus.READY.value,
                TaskStatus.RUNNING.value,
                TaskStatus.REVIEW_PENDING.value,
                TaskStatus.REVIEWING.value,
                TaskStatus.REVISION.value,
            }

    def is_finished(self) -> bool:
        with self._lock:
            return all(
                task.status == TaskStatus.COMPLETED.value
                for task in self.tasks.values()
            )

    def has_failed_tasks(self) -> bool:
        with self._lock:
            return any(
                task.status in {
                    TaskStatus.FAILED.value,
                    TaskStatus.BLOCKED.value,
                }
                for task in self.tasks.values()
            )

    def get_blocked_tasks(self) -> list[Task]:
        with self._lock:
            return [
                task
                for task in self.tasks.values()
                if task.status == TaskStatus.BLOCKED.value
            ]

    def get_failed_tasks(self) -> list[Task]:
        with self._lock:
            return [
                task
                for task in self.tasks.values()
                if task.status == TaskStatus.FAILED.value
            ]

    # ------------------------------------------------------------------
    # Dependency scheduling
    # ------------------------------------------------------------------

    def get_ready_tasks(self) -> list[Task]:
        """
        Promote pending tasks whose dependencies are satisfied.

        The complete readiness decision and resulting mutations happen
        under the same manager lock, so concurrent scheduler calls cannot
        promote one task twice.
        """
        with self._lock:
            ready: list[Task] = []

            for task in self.tasks.values():
                if task.status != TaskStatus.PENDING.value:
                    continue

                missing_dependencies = [
                    dependency_id
                    for dependency_id in task.dependencies
                    if dependency_id not in self.tasks
                ]

                if missing_dependencies:
                    self.mark_blocked(
                        task.id,
                        "Missing dependencies: "
                        + ", ".join(missing_dependencies),
                    )
                    continue

                failed_dependencies = [
                    dependency_id
                    for dependency_id in task.dependencies
                    if self.tasks[dependency_id].status
                    in {
                        TaskStatus.FAILED.value,
                        TaskStatus.BLOCKED.value,
                    }
                ]

                if failed_dependencies:
                    self.mark_blocked(
                        task.id,
                        "Blocked by dependencies: "
                        + ", ".join(failed_dependencies),
                    )
                    continue

                dependencies_completed = all(
                    self.tasks[dependency_id].status
                    == TaskStatus.COMPLETED.value
                    for dependency_id in task.dependencies
                )

                if dependencies_completed:
                    self.mark_ready(task.id)
                    ready.append(task)

            return ready

    def ensure_executable(self, task_id: str) -> Task:
        with self._lock:
            task = self.get_task(task_id)
            if task.status == TaskStatus.PENDING.value:
                self.get_ready_tasks()

            task = self.get_task(task_id)
            if task.status not in {
                TaskStatus.READY.value,
                TaskStatus.RUNNING.value,
            }:
                raise ValueError(
                    f"Task {task_id} is not executable from status "
                    f"{task.status}"
                )
            return task

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    def mark_ready(self, task_id: str) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.READY)
            self.record_error(task_id, None)
            return task

    def mark_running(self, task_id: str) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.RUNNING)
            self.record_error(task_id, None)
            return task

    def mark_developer_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.REVIEW_PENDING)
            self.record_error(task_id, None)
            if result is not None:
                self.record_result(task_id, result)
            return task

    def mark_review_pending(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> Task:
        with self._lock:
            return self.mark_developer_completed(task_id, result)

    def mark_reviewing(self, task_id: str) -> Task:
        with self._lock:
            return self.transition(task_id, TaskStatus.REVIEWING)

    def mark_review_revision_required(
        self,
        task_id: str,
        review_result: dict | Any | None = None,
    ) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.RUNNING)
            if review_result is not None:
                self.record_review_result(task_id, review_result)
                self.set_feedback(task_id, "reviewer", review_result)
            self.record_error(task_id, None)
            return task

    def mark_review_approved(
        self,
        task_id: str,
        review_result: dict | Any,
    ) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.COMPLETED)
            self.record_review_result(task_id, review_result)
            self.record_error(task_id, None)
            return task

    def mark_tester_revision_required(
        self,
        task_id: str,
        test_result: dict | Any,
    ) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.RUNNING)
            self.record_test_result(task_id, test_result)
            self.set_feedback(task_id, "tester", test_result)
            self.record_error(task_id, None)
            return task

    def mark_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> Task:
        with self._lock:
            task = self.transition(task_id, TaskStatus.COMPLETED)
            self.record_error(task_id, None)
            if result is not None:
                self.record_result(task_id, result)
            return task

    def mark_blocked(self, task_id: str, error: str) -> Task:
        if not isinstance(error, str):
            raise TypeError("error must be a string")
        if not error.strip():
            raise ValueError("error must be a non-empty string")

        with self._lock:
            task = self.transition(task_id, TaskStatus.BLOCKED)
            self.record_error(task_id, error)
            return task

    def mark_failed(self, task_id: str, error: str) -> Task:
        if not isinstance(error, str):
            raise TypeError("error must be a string")
        if not error.strip():
            raise ValueError("error must be a non-empty string")

        with self._lock:
            task = self.transition(task_id, TaskStatus.FAILED)
            self.record_error(task_id, error)
            return task

    def retry_task(
        self,
        task_id: str,
        *,
        reason: str,
        retryable: bool,
    ) -> Task:
        """
        Explicitly requeue one failed Task for another execution attempt.

        FAILED remains a terminal state for the generic state machine: this
        operation is the only lifecycle boundary that may reopen it. Retry
        policy is evaluated before any status mutation, so rejected retries
        leave status, error, history, and attempt counters untouched.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("retry reason must be a non-empty string")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean")

        with self._lock:
            task = self.get_task(task_id)
            if task.status != TaskStatus.FAILED.value:
                raise ValueError(
                    f"Task {task_id} cannot be retried from status "
                    f"{task.status}"
                )

            task.record_retry_attempt(
                reason=reason,
                retryable=retryable,
            )

            task.status_history.append(
                {
                    "from": TaskStatus.FAILED.value,
                    "to": TaskStatus.READY.value,
                }
            )
            task.status = TaskStatus.READY.value
            task.error = None
            return task

    # ------------------------------------------------------------------
    # Backward-compatible lifecycle APIs
    # ------------------------------------------------------------------

    def mark_revision(self, task_id: str, review: dict) -> None:
        with self._lock:
            task = self.get_task(task_id)
            if task.status != TaskStatus.REVIEWING.value:
                raise ValueError(f"Task {task_id} is not reviewing")
            self.mark_review_revision_required(task_id, review)

    def mark_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            task = self.get_task(task_id)
            if task.status != TaskStatus.REVIEWING.value:
                raise ValueError(
                    f"Task {task_id} cannot require revision "
                    f"from status {task.status}"
                )
            self.mark_review_revision_required(task_id, review_result)
            if error is not None:
                self.record_error(task_id, error)

    def retry_revision(self, task_id: str) -> None:
        with self._lock:
            task = self.get_task(task_id)
            if task.status != TaskStatus.REVISION.value:
                raise ValueError(f"Task {task_id} is not in revision")
            self.mark_running(task_id)

    def apply_review_result(
        self,
        task_id: str,
        review_result: dict,
    ) -> str:
        with self._lock:
            normalized = self._normalize_result_payload(review_result)
            status = normalized.get("status")

            if status == "approved":
                self.mark_review_approved(task_id, normalized)
                return "completed"

            if status == "revision":
                self.mark_review_revision_required(task_id, normalized)
                return "running"

            raise ValueError(f"Unknown reviewer status: {status}")

    # ------------------------------------------------------------------
    # Result normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_result_payload(result: dict | Any) -> ResultPayload:
        if hasattr(result, "to_dict"):
            result = result.to_dict()

        if not isinstance(result, dict):
            raise TypeError("result must be a dict or support to_dict()")

        payload = dict(result)

        if "data" in payload:
            data = payload["data"]
            if data is None:
                payload["data"] = {}
            elif not isinstance(data, dict):
                raise TypeError("result data must be a dictionary")
            else:
                payload["data"] = dict(data)

        return ResultPayload(payload)

    # ------------------------------------------------------------------
    # Result persistence
    # ------------------------------------------------------------------

    def record_result(self, task_id: str, result: dict | Any) -> Task:
        with self._lock:
            task = self.get_task(task_id)
            task.result = self._normalize_result_payload(result)
            return task

    def record_test_result(
        self,
        task_id: str,
        test_result: dict,
    ) -> Task:
        if not isinstance(test_result, dict):
            raise TypeError("test_result must be a dict")

        with self._lock:
            task = self.get_task(task_id)
            normalized = self._normalize_result_payload(test_result)
            task.test_result = normalized

            if (
                not task.test_history
                or task.test_history[-1] != normalized
            ):
                task.test_history.append(normalized)

            return task

    def record_review_result(
        self,
        task_id: str,
        review_result: dict,
        *,
        increment_round: bool = True,
    ) -> Task:
        if not isinstance(review_result, dict):
            raise TypeError("review_result must be a dict")

        with self._lock:
            task = self.get_task(task_id)
            normalized = self._normalize_result_payload(review_result)
            task.review_result = normalized
            task.review_history.append(normalized)

            if increment_round:
                task.review_round += 1

            return task

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def set_feedback(
        self,
        task_id: str,
        source: str,
        feedback: dict | Any,
    ) -> Task:
        if not isinstance(source, str):
            raise TypeError("feedback source must be a string")
        if not source.strip():
            raise ValueError("feedback source must be a non-empty string")

        with self._lock:
            task = self.get_task(task_id)
            if isinstance(feedback, str):
                normalized_feedback: dict | str = feedback
            else:
                normalized_feedback = self._normalize_result_payload(feedback)

            task.context[f"{source}_feedback"] = normalized_feedback
            return task

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def record_error(
        self,
        task_id: str,
        error: str | None,
    ) -> Task:
        if error is not None and not isinstance(error, str):
            raise TypeError("error must be a string or None")

        with self._lock:
            task = self.get_task(task_id)
            task.error = error
            return task
