from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.agent_context import AgentContext
from runtime.task import Task


class ContextBuilder:
    """Build isolated execution snapshots consumed by Agents."""

    def __init__(self, all_tasks: dict[str, Task] | None = None):
        self.all_tasks = all_tasks or {}

    def build(self, task: Task) -> dict[str, Any]:
        """Build the legacy dictionary-based execution context."""
        self._validate_task(task)
        return {
            "dependencies": self._build_dependency_context(task),
            "tester_feedback": self._build_tester_feedback(task),
            "reviewer_feedback": self._build_reviewer_feedback(task),
        }

    def build_agent_context(
        self,
        task: Task,
        *,
        role: str | None = None,
    ) -> AgentContext:
        """
        Build an AgentContext snapshot for one Agent execution.

        ``dependencies`` remains the compact dependency-ID view.
        ``dependency_context`` contains completed dependency snapshots.

        When ``all_tasks`` is unavailable, an already-built legacy
        ``task.context`` dependency snapshot is used as a compatibility
        source. This keeps the AgentContext migration from silently losing
        Architect -> Developer context without changing Workflow behavior.
        """
        self._validate_task(task)

        context_role = role or task.role

        if not isinstance(context_role, str) or not context_role.strip():
            raise ValueError("AgentContext role must be a non-empty string")

        dependencies = self._build_dependency_context(task)
        tester_feedback = self._build_tester_feedback(task)
        reviewer_feedback = self._build_reviewer_feedback(task)

        return AgentContext(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            role=context_role,
            status=task.status,
            review_round=task.review_round,
            dependencies=list(dependencies.keys()),
            dependency_context=dependencies,
            task_result=deepcopy(task.result),
            tester_feedback=(
                deepcopy(tester_feedback)
                if tester_feedback is not None
                else {}
            ),
            reviewer_feedback=(
                deepcopy(reviewer_feedback)
                if reviewer_feedback is not None
                else {}
            ),
            history=self._build_history(task),
            test_history=self._build_test_history(task),
            review_history=self._build_review_history(task),
            metadata=self._build_metadata(task),
        )

    def _build_dependency_context(self, task: Task) -> dict[str, Any]:
        context: dict[str, Any] = {}

        for dependency_id in task.dependencies:
            dependency = self.all_tasks.get(dependency_id)

            if dependency is not None:
                if dependency.status != "completed":
                    continue

                context[dependency_id] = {
                    "title": dependency.title,
                    "role": dependency.role,
                    "result": deepcopy(dependency.result),
                }
                continue

            # Compatibility path: Workflow may already have materialized
            # the completed dependency snapshot into task.context.
            legacy_context = getattr(task, "context", {})
            if not isinstance(legacy_context, dict):
                continue

            value = legacy_context.get(dependency_id)
            if not isinstance(value, dict):
                continue

            if not {"title", "role", "result"}.issubset(value):
                continue

            context[dependency_id] = deepcopy(value)

        return context

    @staticmethod
    def _build_tester_feedback(task: Task) -> dict[str, Any] | None:
        result = getattr(task, "test_result", None)
        if not result:
            return None
        return deepcopy(result)

    @staticmethod
    def _build_reviewer_feedback(task: Task) -> dict[str, Any] | None:
        result = getattr(task, "review_result", None)
        if not result:
            return None
        return deepcopy(result)

    @staticmethod
    def _build_history(task: Task) -> list[dict[str, Any]]:
        return deepcopy(getattr(task, "status_history", []))

    @staticmethod
    def _build_test_history(task: Task) -> list[dict[str, Any]]:
        return deepcopy(getattr(task, "test_history", []))

    @staticmethod
    def _build_review_history(task: Task) -> list[dict[str, Any]]:
        return deepcopy(getattr(task, "review_history", []))

    @staticmethod
    def _build_metadata(task: Task) -> dict[str, Any]:
        task_context = getattr(task, "context", {})

        if not isinstance(task_context, dict):
            return {}

        reserved = {
            "dependencies",
            "tester_feedback",
            "reviewer_feedback",
        }

        return deepcopy({
            key: value
            for key, value in task_context.items()
            if key not in reserved
            and not (
                isinstance(value, dict)
                and {"title", "role", "result"}.issubset(value)
            )
        })

    @staticmethod
    def _validate_task(task: Task) -> None:
        if not isinstance(task, Task):
            raise TypeError(
                "ContextBuilder expects Task, "
                f"got {type(task).__name__}"
            )


def build_task_context(
    task: Task,
    all_tasks: dict[str, Task],
) -> dict[str, Any]:
    """Backward-compatible functional API."""
    return ContextBuilder(all_tasks).build(task)["dependencies"]
