from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from runtime.metrics import DEFAULT_METRICS, MetricsRegistry
from runtime.multi_project_scheduler import MultiProjectScheduler, ProjectSchedulingRequest
from runtime.project_execution_checkpoint import ProjectExecutionCheckpoint, ProjectExecutionCheckpointStore
from runtime.project_scheduler import ProjectExecutionScope
from runtime.tracing import DEFAULT_TRACER, Tracer
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog

RecoveryOutcome = Literal["completed", "failed", "retry"]


@dataclass(frozen=True)
class ProjectExecutionReservation:
    """Immutable admission handle owned by the execution handoff boundary."""

    reservation_id: str
    request: ProjectSchedulingRequest
    admitted_at: str


class ProjectExecutionHandoff:
    """Bridge project admission into the canonical TaskWorkflow execution path.

    The handoff owns transient reservations. When a checkpoint store is
    configured, the reservation lifecycle is durably mirrored so a restart can
    reconstruct admission state without becoming a second task-state owner.
    """

    def __init__(self, scheduler: MultiProjectScheduler, *, workflow_event_log: WorkflowEventLog | None = None, metrics: MetricsRegistry | None = None, tracer: Tracer | None = None, checkpoint_store: ProjectExecutionCheckpointStore | None = None) -> None:
        if not isinstance(scheduler, MultiProjectScheduler):
            raise TypeError("scheduler must be a MultiProjectScheduler")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if metrics is not None and not isinstance(metrics, MetricsRegistry):
            raise TypeError("metrics must be a MetricsRegistry or None")
        if tracer is not None and not isinstance(tracer, Tracer):
            raise TypeError("tracer must be a Tracer or None")
        if checkpoint_store is not None and not isinstance(checkpoint_store, ProjectExecutionCheckpointStore):
            raise TypeError("checkpoint_store must be a ProjectExecutionCheckpointStore or None")
        self._scheduler = scheduler
        self._workflow_event_log = workflow_event_log
        self._metrics = metrics or DEFAULT_METRICS
        self._tracer = tracer or DEFAULT_TRACER
        self._checkpoint_store = checkpoint_store
        self._reservations: dict[str, ProjectExecutionReservation] = {}
        self._active_by_project: dict[str, int] = {project_id: 0 for project_id in scheduler.project_ids}
        self._lock = RLock()

    @property
    def scheduler(self) -> MultiProjectScheduler:
        return self._scheduler

    @property
    def checkpoint_store(self) -> ProjectExecutionCheckpointStore | None:
        return self._checkpoint_store

    @property
    def active_reservations(self) -> tuple[ProjectExecutionReservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())

    def _emit(self, event_type: str, request: ProjectSchedulingRequest, *, payload: dict[str, Any]) -> None:
        if self._workflow_event_log is None:
            return
        self._workflow_event_log.append(WorkflowEvent(event_id=str(uuid4()), event_type=event_type, project_id=request.scope.project_id, task_id=request.task_id, occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), payload=payload))

    def _metric(self, name: str, request: ProjectSchedulingRequest, *, outcome: str) -> None:
        self._metrics.inc(name, labels={"project_id": request.scope.project_id, "outcome": outcome})

    def _checkpoint(self, reservation: ProjectExecutionReservation, status: str) -> ProjectExecutionCheckpoint:
        scheduler = self._scheduler.scheduler_for(reservation.request.scope.project_id)
        task = scheduler.task_for(reservation.request.task_id)
        return ProjectExecutionCheckpoint(reservation_id=reservation.reservation_id, scope=reservation.request.scope, task_id=reservation.request.task_id, status=status, task_checkpoint=WorkflowCheckpoint.capture(task))

    def _persist_checkpoint(self, reservation: ProjectExecutionReservation, status: str) -> None:
        if self._checkpoint_store is not None:
            self._checkpoint_store.save(self._checkpoint(reservation, status))

    def _reserve(self, reservation: ProjectExecutionReservation) -> None:
        self._reservations[reservation.reservation_id] = reservation
        project_id = reservation.request.scope.project_id
        self._active_by_project[project_id] = self._active_by_project.get(project_id, 0) + 1

    def admit(self, request: ProjectSchedulingRequest) -> ProjectExecutionReservation | None:
        """Attempt a reservation and durably publish it as ``admitted``."""
        if not isinstance(request, ProjectSchedulingRequest):
            raise TypeError("request must be a ProjectSchedulingRequest")
        with self._lock:
            decision = self._scheduler.decide(request)
            if not decision.admitted:
                self._metric("project.scheduler.admission.total", request, outcome="rejected")
                self._emit("project_scheduling_decision", request, payload={"admitted": False, "reason": decision.reason})
                return None
            project_id = request.scope.project_id
            scheduler = self._scheduler.scheduler_for(project_id)
            limit = scheduler.governor.limits.max_concurrent_tasks
            active = self._active_by_project.get(project_id, 0)
            if active >= limit:
                self._metric("project.scheduler.admission.total", request, outcome="rejected")
                self._emit("project_scheduling_decision", request, payload={"admitted": False, "reason": "concurrency resource limit exceeded"})
                return None
            reservation = ProjectExecutionReservation(reservation_id=str(uuid4()), request=request, admitted_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
            self._persist_checkpoint(reservation, "admitted")
            self._reserve(reservation)
            self._metric("project.scheduler.admission.total", request, outcome="admitted")
            self._emit("project_scheduling_decision", request, payload={"admitted": True, "reservation_id": reservation.reservation_id, "active_reservations": active + 1, "max_concurrent_tasks": limit})
            return reservation

    def recover(self) -> tuple[ProjectExecutionReservation, ...]:
        """Reconstruct active reservations from durable recoverable checkpoints.

        Recovery never executes a task or mutates TaskManager state. Returned
        reservations are candidates for authoritative reconciliation.
        """
        if self._checkpoint_store is None:
            return ()
        with self._lock:
            recovered: list[ProjectExecutionReservation] = []
            for checkpoint in self._checkpoint_store.list_recoverable():
                existing = self._reservations.get(checkpoint.reservation_id)
                if existing is not None:
                    recovered.append(existing)
                    continue
                scheduler = self._scheduler.scheduler_for(checkpoint.project_id)
                task = scheduler.task_for(checkpoint.task_id)
                if task.context.get("project_id") not in (None, checkpoint.project_id):
                    raise ValueError("checkpoint task project scope does not match registered project")
                project_id = checkpoint.project_id
                active = self._active_by_project.get(project_id, 0)
                limit = scheduler.governor.limits.max_concurrent_tasks
                if active >= limit:
                    raise RuntimeError(f"cannot recover reservation {checkpoint.reservation_id}: project concurrency resource limit exceeded")
                request = ProjectSchedulingRequest(ProjectExecutionScope(checkpoint.project_id), checkpoint.task_id)
                reservation = ProjectExecutionReservation(reservation_id=checkpoint.reservation_id, request=request, admitted_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
                self._reserve(reservation)
                recovered.append(reservation)
            return tuple(recovered)

    def reconcile(self, reservation: ProjectExecutionReservation, *, outcome: RecoveryOutcome) -> None:
        """Reconcile a recovered execution with an authoritative durable sink.

        ``retry`` deliberately keeps the checkpoint recoverable. This method
        does not select or execute the retry itself.
        """
        if not isinstance(reservation, ProjectExecutionReservation):
            raise TypeError("reservation must be a ProjectExecutionReservation")
        if outcome not in {"completed", "failed", "retry"}:
            raise ValueError("outcome must be 'completed', 'failed', or 'retry'")
        with self._lock:
            existing = self._reservations.get(reservation.reservation_id)
            if existing is None:
                raise ValueError("unknown or already released execution reservation")
            if self._checkpoint_store is None:
                raise ValueError("reconciliation requires a checkpoint store")
            checkpoint = self._checkpoint_store.load(reservation.reservation_id)
            if not checkpoint.recoverable:
                raise ValueError("checkpoint is not recoverable")
            if outcome == "retry":
                self._persist_checkpoint(existing, "started")
                self._emit("project_execution_recovery_reconciled", existing.request, payload={"reservation_id": existing.reservation_id, "outcome": "retry"})
                return
            self._persist_checkpoint(existing, outcome)
            self._emit("project_execution_recovery_reconciled", existing.request, payload={"reservation_id": existing.reservation_id, "outcome": outcome})
            self._release_locked(existing, persist_released=True)

    def release(self, reservation: ProjectExecutionReservation) -> None:
        if not isinstance(reservation, ProjectExecutionReservation):
            raise TypeError("reservation must be a ProjectExecutionReservation")
        with self._lock:
            self._release_locked(reservation, persist_released=True)

    def _release_locked(self, reservation: ProjectExecutionReservation, *, persist_released: bool) -> None:
        existing = self._reservations.get(reservation.reservation_id)
        if existing is None:
            raise ValueError("unknown or already released execution reservation")
        if persist_released and self._checkpoint_store is not None:
            self._persist_checkpoint(existing, "released")
        self._reservations.pop(reservation.reservation_id, None)
        project_id = existing.request.scope.project_id
        active = self._active_by_project.get(project_id, 0)
        self._active_by_project[project_id] = max(0, active - 1)
        self._metric("project.scheduler.reservation.release.total", existing.request, outcome="released")
        self._emit("project_execution_reservation_released", existing.request, payload={"reservation_id": reservation.reservation_id, "active_reservations": self._active_by_project[project_id]})

    def execute(self, request: ProjectSchedulingRequest, workflow) -> Any:
        """Admit once, then invoke the canonical TaskWorkflow.execute method."""
        if not isinstance(request, ProjectSchedulingRequest):
            raise TypeError("request must be a ProjectSchedulingRequest")
        execute = getattr(workflow, "execute", None)
        if not callable(execute):
            raise TypeError("workflow must provide execute(task_id)")
        reservation = self.admit(request)
        if reservation is None:
            raise RuntimeError(f"project execution admission denied for {request.scope.project_id}/{request.task_id}")
        labels = {"project_id": request.scope.project_id, "task_id": request.task_id}
        try:
            with self._tracer.span("project.task.execute", attributes=labels) as span:
                self._persist_checkpoint(reservation, "started")
                self._metric("project.scheduler.execution.total", request, outcome="started")
                self._emit("project_execution_started", request, payload={"reservation_id": reservation.reservation_id})
                result = execute(request.task_id)
                self._persist_checkpoint(reservation, "completed")
                span.set_attribute("execution_outcome", "completed")
                self._metric("project.scheduler.execution.total", request, outcome="completed")
                self._emit("project_execution_completed", request, payload={"reservation_id": reservation.reservation_id})
                return result
        except Exception as exc:
            self._persist_checkpoint(reservation, "failed")
            self._metric("project.scheduler.execution.total", request, outcome="failed")
            self._emit("project_execution_failed", request, payload={"reservation_id": reservation.reservation_id, "error_type": type(exc).__name__})
            raise
        finally:
            self.release(reservation)
