from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from runtime.recovery_observability import RecoveryObservability
from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.task_lease_fencing import FencedLease, FencedTaskLeaseManager
from runtime.workflow_recovery_takeover import RecoveryTakeover, WorkflowRecoveryTakeover


class WorkflowRecoveryRunError(RuntimeError):
    """Raised when a recovered workflow cannot be resumed safely."""


@dataclass(frozen=True)
class RecoveryRunResult:
    task: Task
    takeover: RecoveryTakeover


class WorkflowRecoveryRunner:
    """Resume a recovered workflow while retaining the already-acquired fenced lease."""

    def __init__(
        self,
        workflow,
        lease_manager: FencedTaskLeaseManager,
        *,
        observability: RecoveryObservability | None = None,
    ) -> None:
        if workflow is None or not callable(getattr(workflow, "execute", None)):
            raise TypeError("workflow must provide an execute(task_id) method")
        if not isinstance(lease_manager, FencedTaskLeaseManager):
            raise TypeError("lease_manager must be a FencedTaskLeaseManager")
        if observability is not None and not isinstance(observability, RecoveryObservability):
            raise TypeError("observability must be a RecoveryObservability")
        self._workflow = workflow
        self._leases = lease_manager
        self._takeover = WorkflowRecoveryTakeover(lease_manager)
        self._observability = observability

    def restart(self, checkpoint, assessment, *, owner_id: str, now: datetime | None = None, ttl_seconds: float | None = None) -> RecoveryRunResult:
        takeover = self._takeover.takeover(checkpoint, assessment, owner_id=owner_id, now=now, ttl_seconds=ttl_seconds)
        generation = takeover.lease.generation
        task_id = takeover.task.id
        if self._observability is not None:
            self._observability.takeover(task_id, generation=generation, reason=takeover.decision.reason)
            self._observability.started(task_id, generation=generation)

        task_manager = getattr(self._workflow, "task_manager", None)
        if task_manager is None:
            self._safe_release(takeover)
            if self._observability is not None:
                self._observability.failed(task_id, generation=generation, reason="workflow must expose a task_manager")
            raise WorkflowRecoveryRunError("workflow must expose a task_manager")
        try:
            try:
                current = task_manager.get_task(task_id)
            except (KeyError, AttributeError) as exc:
                raise WorkflowRecoveryRunError("workflow task manager does not contain recovered task") from exc
            if current.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.CANCELLED.value,
            }:
                raise WorkflowRecoveryRunError(f"recovered task became terminal before restart: {current.status}")
            if current.to_dict() != takeover.task.to_dict():
                raise WorkflowRecoveryRunError("workflow task manager state differs from checkpoint")

            result = self._execute_fenced(takeover.lease, task_id, now=now)
            if self._observability is not None:
                self._observability.completed(task_id, generation=generation)
            return RecoveryRunResult(task=result, takeover=takeover)
        except WorkflowRecoveryRunError as exc:
            if self._observability is not None:
                self._observability.failed(task_id, generation=generation, reason=str(exc))
            raise
        except Exception as exc:
            if self._observability is not None:
                self._observability.failed(task_id, generation=generation, reason=str(exc))
            raise WorkflowRecoveryRunError("recovered workflow execution failed") from exc
        finally:
            self._safe_release(takeover)

    def _execute_fenced(self, lease: FencedLease, task_id: str, *, now: datetime | None = None) -> Task:
        self._leases.assert_current(task_id, lease.lease.owner_id, lease.lease.token, lease.generation, now=now)
        result = self._workflow.execute(task_id)
        self._leases.assert_current(task_id, lease.lease.owner_id, lease.lease.token, lease.generation, now=now)
        return result

    def _safe_release(self, takeover: RecoveryTakeover) -> None:
        try:
            self._leases.release(takeover.task.id, takeover.lease.lease.owner_id, takeover.lease.lease.token, takeover.lease.generation)
        except Exception:
            pass


__all__ = ["WorkflowRecoveryRunError", "RecoveryRunResult", "WorkflowRecoveryRunner"]
