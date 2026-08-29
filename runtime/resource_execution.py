from __future__ import annotations

from threading import Lock

from runtime.resource_lifecycle import ResourceLifecycle
from runtime.resource_governor import ResourceGovernor
from runtime.task import Task


class ResourceExecutionCoordinator:
    """Coordinate immutable resource snapshots across concurrent task workers."""

    def __init__(self, governor: ResourceGovernor) -> None:
        if not isinstance(governor, ResourceGovernor):
            raise TypeError("governor must be a ResourceGovernor")
        self._governor = governor
        self._lock = Lock()
        self._active_task_ids: set[str] = set()

    @property
    def governor(self) -> ResourceGovernor:
        with self._lock:
            return self._governor

    def admit(self, task: Task) -> ResourceLifecycle | None:
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        with self._lock:
            if task.cancellation_requested:
                return None
            lifecycle = ResourceLifecycle.admit(task, self._governor)
            if lifecycle is None:
                return None
            self._governor = lifecycle.governor
            self._active_task_ids.add(task.id)
            return lifecycle

    def finish(self, task_id: str) -> ResourceGovernor:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            if task_id not in self._active_task_ids:
                return self._governor
            self._governor = self._governor.finish_task()
            self._active_task_ids.remove(task_id)
            return self._governor

    def cancel(self, task_id: str) -> ResourceGovernor:
        """Release resources held by a cancelled running task.

        Cancellation and resource release are separate operations: callers
        cancel the Task first, then use this idempotent method to release its
        active slot. A task that was never admitted is a no-op.
        """
        return self.finish(task_id)

    def is_active(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._active_task_ids

    @property
    def active_task_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active_task_ids))