from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from runtime.task import Task


class InterruptedWriteError(OSError):
    """Raised when a checkpoint write is interrupted before commit."""


class InterruptedWriteTaskStateStore:
    """Atomic in-memory checkpoint store that preserves the last committed state."""

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = RLock()
        self.fail_next_save_many = False

    def save_many(self, tasks: list[Task]) -> None:
        snapshots: dict[str, dict[str, Any]] = {}
        for task in tasks:
            if not isinstance(task, Task):
                raise TypeError("tasks must contain Task values")
            if task.id in snapshots:
                raise ValueError(f"duplicate task id: {task.id}")
            snapshots[task.id] = deepcopy(task.to_dict())

        if self.fail_next_save_many:
            self.fail_next_save_many = False
            raise InterruptedWriteError("checkpoint write interrupted")

        with self._lock:
            self._states = snapshots

    def load(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._states.get(task_id)
            return deepcopy(state) if state is not None else None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return deepcopy(self._states)
