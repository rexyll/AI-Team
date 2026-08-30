from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.workflow_execution_lease import WorkflowExecutionLease
from runtime.workflow_recovery_takeover import RecoveryTakeover, WorkflowRecoveryTakeover


class WorkflowRecoveryRunError(RuntimeError):
    """Raised when a recovered workflow cannot be resumed safely."""


@dataclass(frozen=True)
class RecoveryRunResult:
    task: Task
    takeover: RecoveryTakeover


class WorkflowRecoveryRunner:
    """Resume a recovered workflow while retaining fenced execution ownership."""

    def __init__(self, workflow, lease_manager: FencedTaskLeaseManager) -> None:
        if workflow is None or not callable(getattr(workflow, "execute", None)):
            raise TypeError("workflow must provide an execute(task_id) method")
        if not isinstance(lease_manager, FencedTaskLeaseManager):
            raise TypeError("lease_manager must be a FencedTaskLeaseManager")
        self._workflow = workflow
        self._leases = lease_manager
        self._takeover = WorkflowRecoveryTakeover(lease_manager)

    def restart(
        self,
        checkpoint,
        assessment,
        *,
        owner_id: str,
        now: datetime | None = None,
        ttl_seconds: float | None = None,
    ) -> RecoveryRunResult:
        takeover = self._takeover.takeover(
            checkpoint,
            assessment,
            owner_id=owner_id,
            now=now,
            ttl_seconds=ttl_seconds,
        )
        task_manager = getattr(self._workflow, "task_manager", None)
        if task_manager is None:
            self._safe_release(takeover)
            raise WorkflowRecoveryRunError("workflow must expose a task_manager")
        try:
            current = task_manager.get_task(takeover.task.id)
        except (KeyError, AttributeError) as exc:
            self._safe_release(takeover)
            raise WorkflowRecoveryRunError("workflow task manager does not contain recovered task") from exc
        if current.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.BLOCKED.value,
            TaskStatus.CANCELLED.value,
        }:
            self._safe_release(takeover)
            raise WorkflowRecoveryRunError(f"recovered task became terminal before restart: {current.status}")
        if current.to_dict() != takeover.task.to_dict():
            self._safe_release(takeover)
            raise WorkflowRecoveryRunError("workflow task manager state differs from checkpoint")

        execution = WorkflowExecutionLease(self._leases, owner_id=owner_id)
        try:
            result = execution.run(
                takeover.task.id,
                lambda lease: self._execute_fenced(lease, takeover.task.id),
                ttl_seconds=ttl_seconds,
                now=now,
            )
            return RecoveryRunResult(task=result, takeover=takeover)
        except Exception as exc:
            raise WorkflowRecoveryRunError("recovered workflow execution failed") from exc

    def _execute_fenced(self, lease, task_id: str) -> Task:
        self._leases.assert_current(task_id, lease.owner_id, lease.token, lease.generation)
        result = self._workflow.execute(task_id)
        self._leases.assert_current(task_id, lease.owner_id, lease.token, lease.generation)
        return result

    def _safe_release(self, takeover: RecoveryTakeover) -> None:
        try:
            self._leases.release(
                takeover.task.id,
                takeover.lease.lease.owner_id,
                takeover.lease.lease.token,
                takeover.lease.generation,
            )
        except Exception:
            pass


__all__ = ["WorkflowRecoveryRunError", "RecoveryRunResult", "WorkflowRecoveryRunner"]
