from __future__ import annotations

from typing import Any

from runtime.workflow import TaskWorkflow
from runtime.workflow_execution_lease import ExecutionLease, WorkflowExecutionLease


class LeaseGuardedTaskWorkflow(TaskWorkflow):
    """TaskWorkflow variant whose whole execution attempt is lease-guarded."""

    def __init__(self, *args: Any, execution_lease: WorkflowExecutionLease, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not isinstance(execution_lease, WorkflowExecutionLease):
            raise TypeError("execution_lease must be a WorkflowExecutionLease")
        self.execution_lease = execution_lease

    def execute(self, task_id: str):
        return self.execution_lease.run(task_id, self._execute_under_lease)

    def _execute_under_lease(self, lease: ExecutionLease):
        # The parent workflow remains the single source of truth for lifecycle
        # transitions. The lease protects the complete execution attempt.
        return super().execute(lease.task_id)


__all__ = ["LeaseGuardedTaskWorkflow"]
