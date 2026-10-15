from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.task import Task
from runtime.workflow import TaskWorkflow


class PluginWorkflowInvocationAdapter:
    """Narrow plugin-facing Workflow boundary backed by ``TaskWorkflow``.

    The plugin supplies only a task identity. The host-owned workflow remains
    responsible for task lookup, stage execution, transitions, retries,
    evidence gates, persistence checkpoints, and workflow events.

    The returned value is a detached persistence-safe task snapshot, so the
    plugin cannot mutate the live ``Task`` or the workflow's internal state.
    """

    def __init__(self, workflow: TaskWorkflow) -> None:
        if not isinstance(workflow, TaskWorkflow):
            raise TypeError("workflow must be a TaskWorkflow")
        self._workflow = workflow

    def execute(self, *, task_id: str) -> dict[str, Any]:
        """Execute one host-owned workflow and return a detached task snapshot."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        task = self._workflow.execute(task_id.strip())
        if not isinstance(task, Task):
            raise TypeError("host Workflow must return Task")
        return deepcopy(task.to_dict())
