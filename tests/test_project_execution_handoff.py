import pytest

from runtime.metrics import MetricsRegistry
from runtime.multi_project_scheduler import MultiProjectScheduler, ProjectSchedulingRequest
from runtime.project_execution_handoff import ProjectExecutionHandoff
from runtime.project_scheduler import ProjectExecutionScope, ProjectScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.tracing import Tracer
from runtime.workflow_event_log import WorkflowEventLog


def _task(task_id: str, project_id: str) -> Task:
    return Task(
        task_id,
        task_id,
        "task",
        "developer",
        status=TaskStatus.PENDING.value,
        context={"project_id": project_id},
    )


def _scheduler(project_id: str, task_id: str, *, max_concurrent_tasks: int = 1) -> ProjectScheduler:
    return ProjectScheduler(
        ProjectExecutionScope(project_id),
        [_task(task_id, project_id)],
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=max_concurrent_tasks)),
    )


class _Workflow:
    def __init__(self, task_id: str = "A", *, error: Exception | None = None):
        self.task_id = task_id
        self.error = error
        self.calls: list[str] = []

    def execute(self, task_id: str):
        self.calls.append(task_id)
        if self.error is not None:
            raise self.error
        return {"task_id": task_id, "status": "completed"}


def _request(project_id: str, task_id: str) -> ProjectSchedulingRequest:
    return ProjectSchedulingRequest(ProjectExecutionScope(project_id), task_id)


def test_admission_reservation_does_not_mutate_task_lifecycle():
    scheduler = _scheduler("P1", "A")
    coordinator = MultiProjectScheduler([scheduler])
    handoff = ProjectExecutionHandoff(coordinator)

    task = scheduler.admissible_tasks()[0]
    before = (task.status, list(task.status_history), dict(task.context))
    reservation = handoff.admit(_request("P1", "A"))

    assert reservation is not None
    assert (task.status, list(task.status_history), dict(task.context)) == before
    assert len(handoff.active_reservations) == 1
    handoff.release(reservation)
    assert handoff.active_reservations == ()


def test_handoff_enforces_project_local_concurrency_without_shared_budget():
    first = _scheduler("P1", "A")
    second = _scheduler("P2", "B")
    handoff = ProjectExecutionHandoff(MultiProjectScheduler([first, second]))

    first_reservation = handoff.admit(_request("P1", "A"))
    assert first_reservation is not None
    assert handoff.admit(_request("P1", "A")) is None
    second_reservation = handoff.admit(_request("P2", "B"))
    assert second_reservation is not None

    handoff.release(first_reservation)
    handoff.release(second_reservation)


def test_execute_uses_canonical_workflow_and_emits_auditable_observability():
    metrics = MetricsRegistry()
    events = WorkflowEventLog(metrics=metrics)
    tracer = Tracer()
    handoff = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler("P1", "A")]),
        workflow_event_log=events,
        metrics=metrics,
        tracer=tracer,
    )
    workflow = _Workflow()

    result = handoff.execute(_request("P1", "A"), workflow)

    assert result == {"task_id": "A", "status": "completed"}
    assert workflow.calls == ["A"]
    assert handoff.active_reservations == ()
    event_types = [event.event_type for event in events.list_for_task("A")]
    assert event_types == [
        "project_scheduling_decision",
        "project_execution_started",
        "project_execution_completed",
        "project_execution_reservation_released",
    ]
    assert all("secret" not in str(event.payload) for event in events.list_for_task("A"))
    assert any(span["name"] == "project.task.execute" and span["status"] == "ok" for span in tracer.snapshot())
    snapshot = metrics.snapshot()["counters"]
    assert "project.scheduler.admission.total" in snapshot
    assert "project.scheduler.execution.total" in snapshot


def test_execute_releases_reservation_and_records_failure_without_changing_task_state():
    metrics = MetricsRegistry()
    events = WorkflowEventLog(metrics=metrics)
    handoff = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler("P1", "A")]),
        workflow_event_log=events,
        metrics=metrics,
        tracer=Tracer(),
    )
    workflow = _Workflow(error=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        handoff.execute(_request("P1", "A"), workflow)

    assert handoff.active_reservations == ()
    failed = [event for event in events.list_for_task("A") if event.event_type == "project_execution_failed"]
    assert len(failed) == 1
    assert failed[0].payload == {
        "reservation_id": failed[0].payload["reservation_id"],
        "error_type": "RuntimeError",
    }
    assert "boom" not in str(failed[0].payload)
    assert any(span["name"] == "project.task.execute" and span["status"] == "error" for span in handoff._tracer.snapshot())


def test_unknown_or_mismatched_requests_are_rejected_at_handoff_boundary():
    handoff = ProjectExecutionHandoff(MultiProjectScheduler([_scheduler("P1", "A")]))

    with pytest.raises(KeyError, match="Unknown project"):
        handoff.admit(_request("P2", "B"))
    with pytest.raises(ValueError, match="does not match"):
        handoff.admit(_request("P2", "A"))
