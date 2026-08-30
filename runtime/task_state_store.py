from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from runtime.task import Task


class InMemoryTaskStateStore:
    """Minimal durable-store contract used by TaskManager recovery tests."""

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def save(self, task: Task) -> None:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        with self._lock:
            self._states[task.id] = deepcopy(task.to_dict())

    def load(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._states.get(task_id)
            return deepcopy(state) if state is not None else None

    def delete(self, task_id: str) -> None:
        with self._lock:
            self._states.pop(task_id, None)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return deepcopy(self._states)
