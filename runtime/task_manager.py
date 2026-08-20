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

    Canonical storage remains exactly the same as AgentResult.to_dict():

        {
            "status": ...,
            "agent": ...,
            "task_id": ...,
            "message": ...,
            "data": {...},
        }

    Legacy callers may still access business fields directly:

        task.result["implementation"]
        task.review_result["approved"]

    Those fields are resolved from ``data`` and are NOT stored as
    additional top-level dictionary keys.
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

        return (
            isinstance(data, dict)
            and key in data
        )

class TaskManager:
    """
    Central owner of Task lifecycle state and task execution data.

    Phase 3 responsibilities
    -------------------------

    TaskManager is the single lifecycle/state-machine facade.

    Responsibilities:

    1. Validate and execute task state transitions.
    2. Manage dependency-driven task readiness/blocking.
    3. Provide explicit lifecycle operations for Workflow.
    4. Persist Agent / Tester / Reviewer results.
    5. Persist execution errors and feedback.
    6. Provide terminal/active/failed/blocked queries.
    7. Preserve compatibility with the previous TaskManager API.

    Important design rule
    ---------------------

    Workflow decides WHAT happened.

    TaskManager decides WHETHER the corresponding state transition
    is legal and persists the resulting task state.

    Example:

        Workflow:
            developer completed

        TaskManager:
            running -> review_pending

    Workflow should never directly mutate:

        task.status
        task.error
        task.result
        task.review_result
        task.test_result
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, tasks: list[Task]):
        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")

        self.tasks: dict[str, Task] = {}

        for task in tasks:
            if not isinstance(task, Task):
                raise TypeError("all tasks must be Task instances")

            if task.id in self.tasks:
                raise ValueError(
                    f"Duplicate task id: {task.id}"
                )

            self.tasks[task.id] = task

    # ------------------------------------------------------------------
    # Basic task access
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Task:
        """
        Return a task by id.
        """
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise KeyError(
                f"Unknown task id: {task_id}"
            ) from exc

    def get_all_tasks(self) -> list[Task]:
        """
        Return all managed tasks.
        """
        return list(self.tasks.values())

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    @staticmethod
    def can_transition(
        current: str | TaskStatus,
        target: str | TaskStatus,
    ) -> bool:
        """
        Return whether a state transition is legal.
        """
        return can_transition(
            current,
            target,
        )

    def transition(
        self,
        task_id: str,
        target_status: str | TaskStatus,
    ) -> Task:
        """
        Perform one validated task state transition.

        This is the ONLY method that mutates Task.status.

        Every successful transition creates a status_history record.
        """

        task = self.get_task(task_id)

        current_status = task.status

        validate_transition(
            current_status,
            target_status,
        )

        if isinstance(target_status, TaskStatus):
            new_status = target_status.value
        else:
            new_status = target_status

        task.status_history.append(
            {
                "from": current_status,
                "to": new_status,
            }
        )

        task.status = new_status

        return task

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_terminal(self, task_id: str) -> bool:
        """
        Return whether the task is in a terminal state.
        """
        task = self.get_task(task_id)

        return task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.BLOCKED.value,
        }

    def is_active(self, task_id: str) -> bool:
        """
        Return whether the task is participating in workflow execution.
        """
        task = self.get_task(task_id)

        return task.status in {
            TaskStatus.READY.value,
            TaskStatus.RUNNING.value,
            TaskStatus.REVIEW_PENDING.value,
            TaskStatus.REVIEWING.value,
            TaskStatus.REVISION.value,
        }

    def is_finished(self) -> bool:
        """
        Return whether every task has completed successfully.

        A blocked or failed task means the workflow is not finished
        successfully.
        """
        return all(
            task.status == TaskStatus.COMPLETED.value
            for task in self.tasks.values()
        )

    def has_failed_tasks(self) -> bool:
        """
        Return whether at least one task failed or was blocked.
        """
        return any(
            task.status in {
                TaskStatus.FAILED.value,
                TaskStatus.BLOCKED.value,
            }
            for task in self.tasks.values()
        )

    def get_blocked_tasks(self) -> list[Task]:
        """
        Return all blocked tasks.
        """
        return [
            task
            for task in self.tasks.values()
            if task.status == TaskStatus.BLOCKED.value
        ]

    def get_failed_tasks(self) -> list[Task]:
        """
        Return all failed tasks.
        """
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

        Dependency rules
        -----------------

        1. Missing dependency:
               pending -> blocked

        2. Failed/blocked dependency:
               pending -> blocked

        3. All dependencies completed:
               pending -> ready

        4. Dependencies still running:
               remain pending

        This method never directly assigns task.status.
        All state changes go through transition().
        """

        ready: list[Task] = []

        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING.value:
                continue

            # ----------------------------------------------------------
            # Missing dependencies
            # ----------------------------------------------------------

            missing_dependencies = [
                dependency_id
                for dependency_id in task.dependencies
                if dependency_id not in self.tasks
            ]

            if missing_dependencies:
                self.mark_blocked(
                    task.id,
                    (
                        "Missing dependencies: "
                        + ", ".join(missing_dependencies)
                    ),
                )
                continue

            # ----------------------------------------------------------
            # Failed / blocked dependencies
            # ----------------------------------------------------------

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
                    (
                        "Blocked by dependencies: "
                        + ", ".join(failed_dependencies)
                    ),
                )
                continue

            # ----------------------------------------------------------
            # All dependencies completed
            # ----------------------------------------------------------

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
        """
        Validate that a task can enter workflow execution.

        Pending tasks are first evaluated against their dependencies.
        """

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
        """
        pending/blocked -> ready
        """
        task = self.transition(
            task_id,
            TaskStatus.READY,
        )

        self.record_error(
            task_id,
            None,
        )

        return task

    def mark_running(self, task_id: str) -> Task:
        """
        ready/revision/review_pending -> running
        """

        task = self.transition(
            task_id,
            TaskStatus.RUNNING,
        )

        self.record_error(
            task_id,
            None,
        )

        return task

    def mark_developer_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> Task:
        """
        Developer successfully completed.

        running -> review_pending
        """

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

        return task

    def mark_review_pending(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> Task:
        """
        Backward-compatible alias for mark_developer_completed().
        """
        return self.mark_developer_completed(
            task_id,
            result,
        )

    def mark_reviewing(self, task_id: str) -> Task:
        """
        review_pending -> reviewing
        """

        return self.transition(
            task_id,
            TaskStatus.REVIEWING,
        )

    def mark_review_revision_required(
        self,
        task_id: str,
        review_result: dict | Any | None = None,
    ) -> Task:
        """
        Reviewer requests Developer revision.

        reviewing -> running
        """

        task = self.transition(
            task_id,
            TaskStatus.RUNNING,
        )

        if review_result is not None:
            self.record_review_result(
                task_id,
                review_result,
            )

            self.set_feedback(
                task_id,
                "reviewer",
                review_result,
            )

        self.record_error(
            task_id,
            None,
        )

        return task

    def mark_review_approved(
        self,
        task_id: str,
        review_result: dict | Any,
    ) -> Task:
        """
        Reviewer approves the task.

        reviewing -> completed
        """

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

        return task

    def mark_tester_revision_required(
        self,
        task_id: str,
        test_result: dict | Any,
    ) -> Task:
        """
        Tester quality gate failed.

        review_pending -> running

        The task is NOT failed because the test failure represents
        a normal Developer revision request.
        """

        task = self.transition(
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

        return task

    def mark_completed(
        self,
        task_id: str,
        result: dict | Any | None = None,
    ) -> Task:
        """
        Complete a task directly.

        Normally used for workflows without review stages.

        running -> completed
        """

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

        return task

    def mark_blocked(
        self,
        task_id: str,
        error: str,
    ) -> Task:
        """
        pending -> blocked

        Also supports the explicit recovery path defined by the
        state machine when called from a state where BLOCKED is legal.
        """

        if not isinstance(error, str):
            raise TypeError(
                "error must be a string"
            )

        if not error.strip():
            raise ValueError(
                "error must be a non-empty string"
            )

        task = self.transition(
            task_id,
            TaskStatus.BLOCKED,
        )

        self.record_error(
            task_id,
            error,
        )

        return task

    def mark_failed(
        self,
        task_id: str,
        error: str,
    ) -> Task:
        """
        Mark task execution as failed.

        The legal source states are defined centrally by
        runtime.task_status.VALID_STATUS_TRANSITIONS.
        """

        if not isinstance(error, str):
            raise TypeError(
                "error must be a string"
            )

        if not error.strip():
            raise ValueError(
                "error must be a non-empty string"
            )

        task = self.transition(
            task_id,
            TaskStatus.FAILED,
        )

        self.record_error(
            task_id,
            error,
        )

        return task

    # ------------------------------------------------------------------
    # Backward-compatible lifecycle APIs
    # ------------------------------------------------------------------

    def mark_revision(
        self,
        task_id: str,
        review: dict,
    ) -> None:
        """
        Legacy compatibility API.

        New Workflow code should use
        mark_review_revision_required().
        """

        task = self.get_task(task_id)

        if task.status != TaskStatus.REVIEWING.value:
            raise ValueError(
                f"Task {task_id} is not reviewing"
            )

        self.mark_review_revision_required(
            task_id,
            review,
        )

    def mark_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
        error: str | None = None,
    ) -> None:
        """
        Legacy compatibility wrapper.

        The current state-machine semantics are:

            reviewing -> running

        for Reviewer revision.

        ``error`` is retained for compatibility but is only recorded
        when explicitly supplied.
        """

        task = self.get_task(task_id)

        if task.status != TaskStatus.REVIEWING.value:
            raise ValueError(
                f"Task {task_id} cannot require revision "
                f"from status {task.status}"
            )

        self.mark_review_revision_required(
            task_id,
            review_result,
        )

        if error is not None:
            self.record_error(
                task_id,
                error,
            )

    def retry_revision(self, task_id: str) -> None:
        """
        Legacy compatibility API.

        Previous implementation used:

            revision -> ready

        The current workflow architecture uses:

            revision -> running

        Therefore this method is retained only as a compatibility
        wrapper and follows the current state-machine semantics.
        """

        task = self.get_task(task_id)

        if task.status != TaskStatus.REVISION.value:
            raise ValueError(
                f"Task {task_id} is not in revision"
            )

        self.mark_running(task_id)

    def apply_review_result(
        self,
        task_id: str,
        review_result: dict,
    ) -> str:
        """
        Apply a reviewer result using the canonical reviewer statuses.

        approved -> completed
        revision -> running
        """

        normalized = self._normalize_result_payload(
            review_result
        )

        status = normalized.get("status")

        if status == "approved":
            self.mark_review_approved(
                task_id,
                normalized,
            )
            return "completed"

        if status == "revision":
            self.mark_review_revision_required(
                task_id,
                normalized,
            )
            return "running"

        raise ValueError(
            f"Unknown reviewer status: {status}"
        )

    # ------------------------------------------------------------------
    # Result normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_result_payload(
        result: dict | Any,
    ) -> ResultPayload:
        """
        Normalize AgentResult or dictionary into the canonical result
        dictionary while preserving legacy business-field access.

        Rules:
        1. AgentResult -> use to_dict().
        2. dict -> preserve its original top-level structure.
        3. If ``data`` exists, it must be a dictionary and is copied.
        4. If ``data`` does not exist, do not create ``data={}``.
        5. ResultPayload provides backward-compatible access to business
        fields stored inside ``data``.
        """

        if hasattr(result, "to_dict"):
            result = result.to_dict()

        if not isinstance(result, dict):
            raise TypeError(
                "result must be a dict or support to_dict()"
            )

        payload = dict(result)

        if "data" in payload:
            data = payload["data"]

            if data is None:
                payload["data"] = {}

            elif not isinstance(data, dict):
                raise TypeError(
                    "result data must be a dictionary"
                )

            else:
                payload["data"] = dict(data)

        return ResultPayload(payload)

    # ------------------------------------------------------------------
    # Result persistence
    # ------------------------------------------------------------------

    def record_result(
        self,
        task_id: str,
        result: dict | Any,
    ) -> Task:
        task = self.get_task(task_id)

        task.result = self._normalize_result_payload(
            result
        )

        return task

    def record_test_result(
        self,
        task_id: str,
        test_result: dict,
    ) -> Task:
        if not isinstance(test_result, dict):
            raise TypeError(
                "test_result must be a dict"
            )

        task = self.get_task(task_id)

        normalized = self._normalize_result_payload(
            test_result
        )

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
            raise TypeError(
                "review_result must be a dict"
            )

        task = self.get_task(task_id)

        normalized = self._normalize_result_payload(
            review_result
        )

        task.review_result = normalized

        # review_history is an event log.
        # Identical results from different review executions
        # must still be recorded independently.
        task.review_history.append(
            normalized
        )

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
        """
        Persist feedback generated by Tester/Reviewer/etc.
        """

        if not isinstance(source, str):
            raise TypeError(
                "feedback source must be a string"
            )

        if not source.strip():
            raise ValueError(
                "feedback source must be a non-empty string"
            )

        task = self.get_task(task_id)

        if isinstance(feedback, str):
            normalized_feedback: dict | str = feedback

        else:
            normalized_feedback = (
                self._normalize_result_payload(
                    feedback
                )
            )

        task.context[
            f"{source}_feedback"
        ] = normalized_feedback

        return task

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def record_error(
        self,
        task_id: str,
        error: str | None,
    ) -> Task:
        """
        Persist or clear task error.
        """

        if error is not None and not isinstance(error, str):
            raise TypeError(
                "error must be a string or None"
            )

        task = self.get_task(task_id)

        task.error = error

        return task

