from runtime.agent_router import AgentRouter
from runtime.multi_project_scheduler import MultiProjectScheduler, ProjectSchedulingRequest
from runtime.project_execution_checkpoint import ProjectExecutionCheckpoint, ProjectExecutionCheckpointStore
from runtime.project_execution_handoff import ProjectExecutionHandoff
from runtime.project_scheduler import ProjectExecutionScope, ProjectScheduler
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus
from runtime.workflow import TaskWorkflow


class _Developer:
    role = "developer"

    def run(self, task):
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implementation complete",
        }


class _Reviewer:
    role = "reviewer"

    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED",
        }


def _task(project_id="P1", task_id="A", status=TaskStatus.READY.value):
    return Task(
        task_id,
        task_id,
        "task",
        "developer",
        status=status,
        context={"project_id": project_id},
    )


def _scheduler(task):
    return ProjectScheduler(
        ProjectExecutionScope(task.context["project_id"]),
        [task],
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)),
    )


def _workflow(manager, task):
    developer = _Developer()
    reviewer = _Reviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    return TaskWorkflow(
        task_manager=manager,
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        project_id=task.context["project_id"],
    )


def _request():
    return ProjectSchedulingRequest(ProjectExecutionScope("P1"), "A")


def test_real_task_workflow_execution_closes_project_checkpoint(tmp_path):
    task = _task()
    manager = TaskManager([task])
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    handoff = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler(task)]),
        checkpoint_store=store,
    )

    result = handoff.execute(_request(), _workflow(manager, task))

    assert result is task
    assert manager.get_task("A").status == TaskStatus.COMPLETED.value
    checkpoints = list(store._records.values())
    assert len(checkpoints) == 1
    assert checkpoints[0].status == "released"
    assert handoff.active_reservations == ()


def test_restart_recovers_ambiguous_started_execution_without_retrying_task(tmp_path):
    task = _task()
    manager = TaskManager([task])
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    first = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler(task)]),
        checkpoint_store=store,
    )

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

    restarted = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler(task)]),
        checkpoint_store=store,
    )
    recovered = restarted.recover()

    assert len(recovered) == 1
    assert manager.get_task("A").status == TaskStatus.READY.value
    assert len(restarted.active_reservations) == 1
    assert store.load(reservation.reservation_id).status == "started"

    restarted.reconcile(recovered[0], outcome="completed")

    assert manager.get_task("A").status == TaskStatus.READY.value
    assert restarted.active_reservations == ()
    assert store.load(reservation.reservation_id).status == "released"


def test_authoritative_task_manager_terminal_state_prevents_ambiguous_retry(tmp_path):
    task = _task()
    manager = TaskManager([task])
    store = ProjectExecutionCheckpointStore(tmp_path / "checkpoints")
    first = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler(task)]),
        checkpoint_store=store,
    )

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

    manager._recover_terminal_state(
        "A",
        TaskStatus.COMPLETED,
        reason="authoritative durable result recovered after process restart",
    )
    restarted = ProjectExecutionHandoff(
        MultiProjectScheduler([_scheduler(task)]),
        checkpoint_store=store,
    )
    recovered = restarted.recover()
    assert len(recovered) == 1

    restarted.reconcile(recovered[0], outcome="retry")
    assert manager.get_task("A").status == TaskStatus.COMPLETED.value
    assert store.load(reservation.reservation_id).status == "started"
