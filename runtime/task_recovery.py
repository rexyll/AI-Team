from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from runtime.task import Task


class TaskRecoveryError(ValueError):
    """Raised when persisted task state cannot be safely recovered."""


class TaskRecovery:
    """Loads validated task snapshots without producing lifecycle transitions."""

    def __init__(self, state_store) -> None:
        if state_store is None:
            raise ValueError("state_store is required")
        self._state_store = state_store

    def recover(self, task_id: str) -> Task:
        snapshot = self._state_store.load(task_id)
        if snapshot is None:
            raise TaskRecoveryError(f"persisted task not found: {task_id}")
        return self._from_snapshot(snapshot)

    def recover_many(self, task_ids: Iterable[str]) -> list[Task]:
        return [self.recover(task_id) for task_id in task_ids]

    @staticmethod
    def _from_snapshot(snapshot: dict) -> Task:
        if not isinstance(snapshot, dict):
            raise TaskRecoveryError("persisted task snapshot must be an object")
        try:
            task = Task.from_dict(deepcopy(snapshot))
        except (TypeError, ValueError, KeyError) as exc:
            raise TaskRecoveryError("invalid persisted task snapshot") from exc
        if not task.id:
            raise TaskRecoveryError("persisted task id must be non-empty")
        return task
