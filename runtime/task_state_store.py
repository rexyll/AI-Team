from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Protocol

from runtime.task import Task


class TaskStateStore(Protocol):
    """Canonical durable snapshot boundary for TaskManager state.

    TaskManager remains the authoritative live-state owner. Implementations of
    this protocol only persist detached task snapshots and must never mutate
    the supplied Task objects.
    """

    def save(self, task: Task) -> None:
        ...

    def save_many(self, tasks: list[Task]) -> None:
        ...

    def load(self, task_id: str) -> dict[str, Any] | None:
        ...

    def snapshot(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryTaskStateStore:
    """Atomic in-memory implementation of the canonical TaskStateStore."""

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def save(self, task: Task) -> None:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        snapshot = deepcopy(task.to_dict())
        with self._lock:
            self._states[task.id] = snapshot

    def save_many(self, tasks: list[Task]) -> None:
        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")
        snapshots: dict[str, dict[str, Any]] = {}
        for task in tasks:
            if not isinstance(task, Task):
                raise TypeError("tasks must contain Task values")
            if task.id in snapshots:
                raise ValueError(f"duplicate task id: {task.id}")
            snapshots[task.id] = deepcopy(task.to_dict())
        with self._lock:
            self._states.update(snapshots)

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
