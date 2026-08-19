from __future__ import annotations

from typing import Any

from runtime.task import Task


class ContextBuilder:
    """
    Build the execution context consumed by agents.

    Responsibilities:
    - expose completed dependency results
    - expose the latest tester feedback
    - expose the latest reviewer feedback

    Non-responsibilities:
    - do not modify Task
    - do not change task status
    - do not execute agents
    - do not control workflow transitions
    """

    def __init__(self, all_tasks: dict[str, Task] | None = None):
        self.all_tasks = all_tasks or {}

    def build(self, task: Task) -> dict[str, Any]:
        """
        Build a read-only snapshot of the information currently
        relevant to the agent executing the task.
        """
        return {
            "dependencies": self._build_dependency_context(task),
            "tester_feedback": self._build_tester_feedback(task),
            "reviewer_feedback": self._build_reviewer_feedback(task),
        }

    def _build_dependency_context(self, task: Task) -> dict[str, Any]:
        context: dict[str, Any] = {}

        for dependency_id in task.dependencies:
            dependency = self.all_tasks.get(dependency_id)

            if dependency is None:
                continue

            if dependency.status != "completed":
                continue

            context[dependency_id] = {
                "title": dependency.title,
                "role": dependency.role,
                "result": dependency.result,
            }

        return context

    @staticmethod
    def _build_tester_feedback(
        task: Task,
    ) -> dict[str, Any] | None:
        result = getattr(task, "test_result", None)

        if not result:
            return None

        return dict(result)

    @staticmethod
    def _build_reviewer_feedback(
        task: Task,
    ) -> dict[str, Any] | None:
        result = getattr(task, "review_result", None)

        if not result:
            return None

        return dict(result)


def build_task_context(
    task: Task,
    all_tasks: dict[str, Task],
) -> dict[str, Any]:
    """
    Backward-compatible functional API.

    Existing callers can continue using:

        build_task_context(task, all_tasks)

    The legacy API returns only completed dependency context:

        {
            "TASK-001": {
                "title": "...",
                "role": "...",
                "result": {...},
            }
        }

    New code should prefer:

        ContextBuilder(all_tasks).build(task)
    """
    return ContextBuilder(all_tasks).build(task)["dependencies"]