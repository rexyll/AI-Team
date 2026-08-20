from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.agent_context import AgentContext
from runtime.task import Task


class ContextBuilder:
    """
    Build execution snapshots consumed by Agents.

    Responsibilities:
    - expose completed dependency results
    - expose the latest tester feedback
    - expose the latest reviewer feedback
    - construct AgentContext snapshots

    Non-responsibilities:
    - do not modify Task
    - do not change task status
    - do not execute Agents
    - do not control workflow transitions
    """

    def __init__(
        self,
        all_tasks: dict[str, Task] | None = None,
    ):
        self.all_tasks = all_tasks or {}

    def build(
        self,
        task: Task,
    ) -> dict[str, Any]:
        """
        Build the legacy dictionary-based execution context.

        This method remains backward compatible.

        New Agent-facing code should prefer:

            build_agent_context(task)
        """
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

        The returned AgentContext is detached from the source Task.
        Later mutations to Task or its nested dictionaries/lists will
        not modify the returned context.
        """
        self._validate_task(task)

        context_role = role or task.role

        if not isinstance(context_role, str) or not context_role.strip():
            raise ValueError(
                "AgentContext role must be a non-empty string"
            )

        dependencies = self._build_dependency_context(task)

        tester_feedback = self._build_tester_feedback(task)

        reviewer_feedback = self._build_reviewer_feedback(task)

        history = self._build_history(task)

        metadata = self._build_metadata(task)

        return AgentContext(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            role=context_role,
            status=task.status,
            review_round=task.review_round,
            dependencies=list(dependencies.keys()),
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
            history=history,
            metadata=metadata,
        )

    def _build_dependency_context(
        self,
        task: Task,
    ) -> dict[str, Any]:
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
                "result": deepcopy(dependency.result),
            }

        return context

    @staticmethod
    def _build_tester_feedback(
        task: Task,
    ) -> dict[str, Any] | None:
        result = getattr(task, "test_result", None)

        if not result:
            return None

        return deepcopy(result)

    @staticmethod
    def _build_reviewer_feedback(
        task: Task,
    ) -> dict[str, Any] | None:
        result = getattr(task, "review_result", None)

        if not result:
            return None

        return deepcopy(result)

    @staticmethod
    def _build_history(
        task: Task,
    ) -> list[dict[str, Any]]:
        """
        Build a detached execution history snapshot.

        status_history is the authoritative generic Task lifecycle
        history, while test/review histories remain represented by
        their dedicated feedback fields.
        """
        return deepcopy(
            getattr(task, "status_history", [])
        )

    @staticmethod
    def _build_metadata(
        task: Task,
    ) -> dict[str, Any]:
        """
        Preserve non-core Task context as AgentContext metadata.

        Known context-builder fields are excluded because they have
        dedicated AgentContext fields.
        """
        task_context = getattr(task, "context", {})

        if not isinstance(task_context, dict):
            return {}

        reserved = {
            "dependencies",
            "tester_feedback",
            "reviewer_feedback",
        }

        return deepcopy(
            {
                key: value
                for key, value in task_context.items()
                if key not in reserved
            }
        )

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

        ContextBuilder(all_tasks).build_agent_context(task)
    """
    return ContextBuilder(all_tasks).build(task)["dependencies"]