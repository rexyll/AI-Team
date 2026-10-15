from __future__ import annotations

from typing import Callable, TypeVar

from runtime.workflow_execution_lease import ExecutionLease, WorkflowExecutionLease

T = TypeVar("T")


class LeaseGuardedExecutor:
    """Apply an execution lease around an existing task execution callable."""

    def __init__(self, execution_lease: WorkflowExecutionLease) -> None:
        if not isinstance(execution_lease, WorkflowExecutionLease):
            raise TypeError("execution_lease must be a WorkflowExecutionLease")
        self.execution_lease = execution_lease

    def execute(self, task_id: str, action: Callable[[ExecutionLease], T]) -> T:
        return self.execution_lease.run(task_id, action)
