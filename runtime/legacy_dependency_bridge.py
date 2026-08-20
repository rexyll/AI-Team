from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.task import Task


class LegacyDependencyBridge:
    """Resolve completed dependency snapshots with canonical-first semantics.

    The bridge is the only compatibility adapter allowed to read legacy
    ``Task.context`` dependency entries. Canonical ``all_tasks`` snapshots
    always win; legacy entries are used only when the canonical dependency
    is unavailable.
    """

    REQUIRED_KEYS = frozenset({"title", "role", "result"})

    def __init__(self, all_tasks: dict[str, Task] | None = None):
        self.all_tasks = all_tasks or {}

    def build(self, task: Task) -> dict[str, Any]:
        """Return completed dependency snapshots for declared dependencies."""
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

            legacy_snapshot = self._legacy_snapshot(task, dependency_id)
            if legacy_snapshot is not None:
                context[dependency_id] = legacy_snapshot

        return context

    @classmethod
    def _legacy_snapshot(
        cls,
        task: Task,
        dependency_id: str,
    ) -> dict[str, Any] | None:
        task_context = getattr(task, "context", {})
        if not isinstance(task_context, dict):
            return None

        value = task_context.get(dependency_id)
        if not isinstance(value, dict):
            return None

        if not cls.REQUIRED_KEYS.issubset(value):
            return None

        return deepcopy(value)


def build_legacy_dependency_context(
    task: Task,
    all_tasks: dict[str, Task],
) -> dict[str, Any]:
    """Compatibility API used by Workflow while the bridge is retired."""
    return LegacyDependencyBridge(all_tasks).build(task)
