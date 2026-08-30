from __future__ import annotations

from copy import deepcopy

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_recovery import TaskRecovery
from runtime.task_status import TaskStatus, validate_transition


class PersistentTaskManager(TaskManager):
    """TaskManager variant that durably persists lifecycle mutations."""

    def __init__(self, tasks: list[Task], *, state_store, result_store=None, persist_initial=True):
        if state_store is None:
            raise ValueError("state_store is required")
        super().__init__(tasks, result_store=result_store)
        self.state_store = state_store
        if persist_initial:
            for task in self.tasks.values():
                self._persist_state(task)

    @classmethod
    def from_state_store(cls, state_store, *, result_store=None):
        """Bootstrap entirely from durable task snapshots without creating transitions."""
        recovery = TaskRecovery(state_store)
        snapshots = state_store.snapshot()
        tasks = [recovery.recover(task_id) for task_id in snapshots]
        return cls(tasks, state_store=state_store, result_store=result_store, persist_initial=False)

    def _persist_state(self, task: Task) -> None:
        self.state_store.save(task)

    def transition(self, task_id: str, target_status: str | TaskStatus) -> Task:
        with self._lock:
            task = self.get_task(task_id)
            before = deepcopy(task.to_dict())
            current = task.status
            validate_transition(current, target_status)
            new_status = target_status.value if isinstance(target_status, TaskStatus) else target_status
            try:
                task.status_history.append({"from": current, "to": new_status})
                task.status = new_status
                self._persist_state(task)
            except Exception:
                restored = Task.from_dict(before)
                for key, value in restored.__dict__.items():
                    setattr(task, key, value)
                for key in tuple(task.__dict__):
                    if key not in restored.__dict__:
                        delattr(task, key)
                raise
            return task
