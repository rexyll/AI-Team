from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime.task import Task


class WorkflowCheckpointError(ValueError):
    """Raised when a workflow checkpoint is missing or invalid."""


@dataclass(frozen=True)
class WorkflowCheckpoint:
    """Validated, immutable-in-interface snapshot of workflow execution state."""

    task_id: str
    task: dict[str, Any]
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise WorkflowCheckpointError("task_id must be a non-empty string")
        if not isinstance(self.version, int) or self.version != 1:
            raise WorkflowCheckpointError("unsupported checkpoint version")
        if not isinstance(self.task, dict):
            raise WorkflowCheckpointError("task snapshot must be an object")
        if self.task.get("id") != self.task_id:
            raise WorkflowCheckpointError("checkpoint task_id does not match task snapshot")

    @classmethod
    def capture(cls, task: Task) -> "WorkflowCheckpoint":
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        return cls(task_id=task.id, task=deepcopy(task.to_dict()))

    def restore(self) -> Task:
        try:
            task = Task.from_dict(deepcopy(self.task))
        except (TypeError, ValueError, KeyError) as exc:
            raise WorkflowCheckpointError("invalid workflow checkpoint") from exc
        if task.id != self.task_id:
            raise WorkflowCheckpointError("restored task id mismatch")
        return task

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "task_id": self.task_id,
            "task": deepcopy(self.task),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowCheckpoint":
        if not isinstance(payload, dict):
            raise WorkflowCheckpointError("checkpoint must be an object")
        return cls(
            version=payload.get("version", 0),
            task_id=payload.get("task_id", ""),
            task=deepcopy(payload.get("task")),
        )
