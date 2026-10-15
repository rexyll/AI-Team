from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.agent_context import AgentContext
from runtime.legacy_dependency_bridge import LegacyDependencyBridge
from runtime.task import Task
from runtime.task_checkpoint import build_task_checkpoint_summary
from security.secrets import redact_value


class ContextBuilder:
    """Build isolated execution snapshots consumed by Agents."""

    def __init__(self, all_tasks: dict[str, Task] | None = None):
        self.all_tasks = all_tasks or {}
        self._dependency_bridge = LegacyDependencyBridge(self.all_tasks)

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

        Legacy ``Task.context`` dependency data is read only through the
        dedicated compatibility bridge and only when canonical task data is
        unavailable.
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
            dependency_context=redact_value(dependencies),
            task_result=redact_value(deepcopy(task.result)),
            tester_feedback=(
                redact_value(deepcopy(tester_feedback))
                if tester_feedback is not None
                else {}
            ),
            reviewer_feedback=(
                redact_value(deepcopy(reviewer_feedback))
                if reviewer_feedback is not None
                else {}
            ),
            history=redact_value(self._build_history(task)),
            test_history=redact_value(self._build_test_history(task)),
            review_history=redact_value(self._build_review_history(task)),
            metadata=redact_value(self._build_metadata(task, role=context_role)),
        )

    def _build_dependency_context(self, task: Task) -> dict[str, Any]:
        return self._dependency_bridge.build(task)

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
    def _build_metadata(task: Task, *, role: str | None = None) -> dict[str, Any]:
        task_context = getattr(task, "context", {})

        if not isinstance(task_context, dict):
            task_context = {}

        reserved = {
            "dependencies",
            "tester_feedback",
            "reviewer_feedback",
            "tool_execution_history",
        }

        metadata = deepcopy({
            key: value
            for key, value in task_context.items()
            if key not in reserved
            and not (
                isinstance(value, dict)
                and {"title", "role", "result"}.issubset(value)
            )
        })

        if role == "developer":
            result = getattr(task, "result", {})
            if isinstance(result, dict):
                data = result.get("data", result)
                if isinstance(data, dict):
                    telemetry = data.get("tool_loop_telemetry", [])
                    changed_files = data.get("files_changed", [])
                    command_results = data.get("tests", [])
                    if isinstance(telemetry, list) and (
                        telemetry or changed_files or command_results
                    ):
                        checkpoint = build_task_checkpoint_summary(
                            task_id=task.id,
                            status=task.status,
                            telemetry=telemetry,
                            changed_files=changed_files,
                            command_results=command_results,
                            dependency_context={},
                            task_result={},
                        )
                        metadata["task_checkpoint"] = checkpoint.to_dict()

        return metadata

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
) -> dict[str, Any] | list[str]:
    """Backward-compatible functional API."""
    if not task.dependencies:
        return []
    return LegacyDependencyBridge(all_tasks).build(task)
