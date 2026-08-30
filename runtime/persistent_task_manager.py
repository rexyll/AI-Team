from __future__ import annotations

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus, validate_transition


class PersistentTaskManager(TaskManager):
    """TaskManager variant that durably persists lifecycle mutations."""

    def __init__(self, tasks: list[Task], *, state_store, result_store=None):
        if state_store is None:
            raise ValueError("state_store is required")
        super().__init__(tasks, result_store=result_store)
        self.state_store = state_store
        for task in self.tasks.values():
            self._persist_state(task)

    def _persist_state(self, task: Task) -> None:
        self.state_store.save(task)

    def transition(self, task_id: str, target_status: str | TaskStatus) -> Task:
        with self._lock:
            task = self.get_task(task_id)
            before = task.to_dict()
            current = task.status
            validate_transition(current, target_status)
            new_status = target_status.value if isinstance(target_status, TaskStatus) else target_status
            try:
                task.status_history.append({"from": current, "to": new_status})
                task.status = new_status
                self._persist_state(task)
            except Exception:
                restored = Task.from_dict(before)
                task.__dict__.clear()
                task.__dict__.update(restored.__dict__)
                raise
            return task
