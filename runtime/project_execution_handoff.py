from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from runtime.metrics import DEFAULT_METRICS, MetricsRegistry
from runtime.multi_project_scheduler import MultiProjectScheduler, ProjectSchedulingRequest
from runtime.tracing import DEFAULT_TRACER, Tracer
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


@dataclass(frozen=True)
class ProjectExecutionReservation:
    """Immutable admission handle owned by the execution handoff boundary."""

    reservation_id: str
    request: ProjectSchedulingRequest
    admitted_at: str


class ProjectExecutionHandoff:
    """Bridge project admission into the canonical TaskWorkflow execution path.

    The handoff owns only transient reservations. ProjectScheduler and
    MultiProjectScheduler remain pure decision layers; TaskManager remains the
    canonical owner of task lifecycle state.
    """

    def __init__(
        self,
        scheduler: MultiProjectScheduler,
        *,
        workflow_event_log: WorkflowEventLog | None = None,
        metrics: MetricsRegistry | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        if not isinstance(scheduler, MultiProjectScheduler):
            raise TypeError("scheduler must be a MultiProjectScheduler")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if metrics is not None and not isinstance(metrics, MetricsRegistry):
            raise TypeError("metrics must be a MetricsRegistry or None")
        if tracer is not None and not isinstance(tracer, Tracer):
            raise TypeError("tracer must be a Tracer or None")
        self._scheduler = scheduler
        self._workflow_event_log = workflow_event_log
        self._metrics = metrics or DEFAULT_METRICS
        self._tracer = tracer or DEFAULT_TRACER
        self._reservations: dict[str, ProjectExecutionReservation] = {}
        self._active_by_project: dict[str, int] = {project_id: 0 for project_id in scheduler.project_ids}
        self._lock = RLock()

    @property
    def scheduler(self) -> MultiProjectScheduler:
        return self._scheduler

    @property
    def active_reservations(self) -> tuple[ProjectExecutionReservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())

    def _emit(self, event_type: str, request: ProjectSchedulingRequest, *, payload: dict[str, Any]) -> None:
        if self._workflow_event_log is None:
            return
        self._workflow_event_log.append(
            WorkflowEvent(
                event_id=str(uuid4()),
                event_type=event_type,
                project_id=request.scope.project_id,
                task_id=request.task_id,
                occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                payload=payload,
            )
        )

    def _metric(self, name: str, request: ProjectSchedulingRequest, *, outcome: str) -> None:
        self._metrics.inc(
            name,
            labels={
                "project_id": request.scope.project_id,
                "outcome": outcome,
            },
        )

    def admit(self, request: ProjectSchedulingRequest) -> ProjectExecutionReservation | None:
        """Attempt a transient execution reservation without changing Task state."""
        if not isinstance(request, ProjectSchedulingRequest):
            raise TypeError("request must be a ProjectSchedulingRequest")
        with self._lock:
            decision = self._scheduler.decide(request)
            if not decision.admitted:
                self._metric("project.scheduler.admission.total", request, outcome="rejected")
                self._emit(
                    "project_scheduling_decision",
                    request,
                    payload={"admitted": False, "reason": decision.reason},
                )
                return None

            project_id = request.scope.project_id
            scheduler = self._scheduler.scheduler_for(project_id)
            limit = scheduler.governor.limits.max_concurrent_tasks
            active = self._active_by_project.get(project_id, 0)
            if active >= limit:
                self._metric("project.scheduler.admission.total", request, outcome="rejected")
                self._emit(
                    "project_scheduling_decision",
                    request,
                    payload={"admitted": False, "reason": "concurrency resource limit exceeded"},
                )
                return None

            reservation = ProjectExecutionReservation(
                reservation_id=str(uuid4()),
                request=request,
                admitted_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
            self._reservations[reservation.reservation_id] = reservation
            self._active_by_project[project_id] = active + 1
            self._metric("project.scheduler.admission.total", request, outcome="admitted")
            self._emit(
                "project_scheduling_decision",
                request,
                payload={
                    "admitted": True,
                    "reservation_id": reservation.reservation_id,
                    "active_reservations": active + 1,
                    "max_concurrent_tasks": limit,
                },
            )
            return reservation

    def release(self, reservation: ProjectExecutionReservation) -> None:
        if not isinstance(reservation, ProjectExecutionReservation):
            raise TypeError("reservation must be a ProjectExecutionReservation")
        with self._lock:
            existing = self._reservations.pop(reservation.reservation_id, None)
            if existing is None:
                raise ValueError("unknown or already released execution reservation")
            project_id = existing.request.scope.project_id
            active = self._active_by_project.get(project_id, 0)
            self._active_by_project[project_id] = max(0, active - 1)
            self._metric("project.scheduler.reservation.release.total", existing.request, outcome="released")
            self._emit(
                "project_execution_reservation_released",
                existing.request,
                payload={"reservation_id": reservation.reservation_id, "active_reservations": self._active_by_project[project_id]},
            )

    def execute(self, request: ProjectSchedulingRequest, workflow) -> Any:
        """Admit once, then invoke the canonical TaskWorkflow.execute method."""
        if not isinstance(request, ProjectSchedulingRequest):
            raise TypeError("request must be a ProjectSchedulingRequest")
        execute = getattr(workflow, "execute", None)
        if not callable(execute):
            raise TypeError("workflow must provide execute(task_id)")

        reservation = self.admit(request)
        if reservation is None:
            raise RuntimeError(
                f"project execution admission denied for {request.scope.project_id}/{request.task_id}"
            )

        labels = {"project_id": request.scope.project_id, "task_id": request.task_id}
        try:
            with self._tracer.span("project.task.execute", attributes=labels) as span:
                self._metric("project.scheduler.execution.total", request, outcome="started")
                self._emit(
                    "project_execution_started",
                    request,
                    payload={"reservation_id": reservation.reservation_id},
                )
                result = execute(request.task_id)
                span.set_attribute("execution_outcome", "completed")
                self._metric("project.scheduler.execution.total", request, outcome="completed")
                self._emit(
                    "project_execution_completed",
                    request,
                    payload={"reservation_id": reservation.reservation_id},
                )
                return result
        except Exception as exc:
            self._metric("project.scheduler.execution.total", request, outcome="failed")
            self._emit(
                "project_execution_failed",
                request,
                payload={"reservation_id": reservation.reservation_id, "error_type": type(exc).__name__},
            )
            raise
        finally:
            self.release(reservation)
