from runtime.multi_project_scheduler import MultiProjectScheduler, ProjectSchedulingRequest
from runtime.project_execution_checkpoint import ProjectExecutionCheckpoint, ProjectExecutionCheckpointStore
from runtime.project_execution_handoff import ProjectExecutionHandoff
from runtime.project_scheduler import ProjectExecutionScope, ProjectScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus


def _scheduler(project_id: str = "P1", task_id: str = "A") -> ProjectScheduler:
    task = Task(
        task_id,
        task_id,
        "task",
        "developer",
        status=TaskStatus.PENDING.value,
        context={"project_id": project_id},
    )
    return ProjectScheduler(
        ProjectExecutionScope(project_id),
        [task],
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
    )


def _handoff(store: ProjectExecutionCheckpointStore) -> ProjectExecutionHandoff:
    return ProjectExecutionHandoff(MultiProjectScheduler([_scheduler()]), checkpoint_store=store)


def _request() -> ProjectSchedulingRequest:
    return ProjectSchedulingRequest(ProjectExecutionScope("P1"), "A")


def test_admission_and_release_are_durably_mirrored(tmp_path):
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    handoff = _handoff(store)

    reservation = handoff.admit(_request())
    assert reservation is not None
    assert store.load(reservation.reservation_id).status == "admitted"

    handoff.release(reservation)
    assert store.load(reservation.reservation_id).status == "released"
    assert store.list_recoverable() == ()


def test_restart_reconstructs_recoverable_reservation_without_executing(tmp_path):
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    first = _handoff(store)

    reservation = first.admit(_request())
    assert reservation is not None
    checkpoint = store.load(reservation.reservation_id)
    store.save(
        ProjectExecutionCheckpoint(
            reservation_id=checkpoint.reservation_id,
            scope=checkpoint.scope,
            task_id=checkpoint.task_id,
            status="started",
            task_checkpoint=checkpoint.task_checkpoint,
        )
    )
    first.release(reservation)
    store.save(
        ProjectExecutionCheckpoint(
            reservation_id=checkpoint.reservation_id,
            scope=checkpoint.scope,
            task_id=checkpoint.task_id,
            status="started",
            task_checkpoint=checkpoint.task_checkpoint,
        )
    )

    second = _handoff(store)
    recovered = second.recover()

    assert len(recovered) == 1
    assert recovered[0].reservation_id == reservation.reservation_id
    assert recovered[0].request.task_id == "A"
    assert len(second.active_reservations) == 1


def test_recovered_execution_requires_authoritative_reconciliation(tmp_path):
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    handoff = _handoff(store)

    reservation = handoff.admit(_request())
    assert reservation is not None
    checkpoint = store.load(reservation.reservation_id)
    store.save(
        ProjectExecutionCheckpoint(
            reservation_id=checkpoint.reservation_id,
            scope=checkpoint.scope,
            task_id=checkpoint.task_id,
            status="started",
            task_checkpoint=checkpoint.task_checkpoint,
        )
    )

    handoff.reconcile(reservation, outcome="retry")
    assert store.load(reservation.reservation_id).status == "started"
    assert len(handoff.active_reservations) == 1

    handoff.reconcile(reservation, outcome="completed")
    assert store.load(reservation.reservation_id).status == "released"
    assert handoff.active_reservations == ()
