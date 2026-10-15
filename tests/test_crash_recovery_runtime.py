import json

from runtime.crash_recovery import RecoveryAction
from runtime.crash_recovery_runtime import CrashRecoveryCoordinator
from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_persistence import TaskPersistenceAdapter


def _task(task_id: str, status: str) -> Task:
    task = Task(id=task_id, title=task_id, description="test", role="developer")
    task.status = status
    return task


def test_crash_recovery_releases_interrupted_resource_and_does_not_mutate_persisted_task(tmp_path):
    persistence = TaskPersistenceAdapter(tmp_path)
    task = _task("TASK-001", "running")
    persistence.save(task)

    resources = ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)))
    live_task = persistence.load("TASK-001")
    assert resources.admit(live_task) is not None

    report = CrashRecoveryCoordinator(persistence, resources).inspect()

    assert report.recoverable_task_ids == ("TASK-001",)
    assert report.released_task_ids == ("TASK-001",)
    assert resources.governor.usage.active_tasks == 0
    assert persistence.load("TASK-001").status == "running"


def test_crash_recovery_is_idempotent_for_already_released_resources(tmp_path):
    persistence = TaskPersistenceAdapter(tmp_path)
    task = _task("TASK-001", "running")
    persistence.save(task)
    resources = ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)))

    first = CrashRecoveryCoordinator(persistence, resources).inspect()
    second = CrashRecoveryCoordinator(persistence, resources).inspect()

    assert first.released_task_ids == ()
    assert second.released_task_ids == ()
    assert resources.governor.usage.active_tasks == 0


def test_crash_recovery_never_replays_terminal_task(tmp_path):
    persistence = TaskPersistenceAdapter(tmp_path)
    completed = _task("TASK-001", "completed")
    failed = _task("TASK-002", "failed")
    cancelled = _task("TASK-003", "cancelled")
    for task in (completed, failed, cancelled):
        persistence.save(task)

    report = CrashRecoveryCoordinator(
        persistence,
        ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=3))),
    ).inspect()

    assert report.recoverable_task_ids == ()
    assert report.released_task_ids == ()
    assert report.terminal_task_ids == ("TASK-001", "TASK-002", "TASK-003")
    assert all(d.action == RecoveryAction.NOOP for d in report.decisions)


def test_crash_recovery_can_target_subset_without_mutation(tmp_path):
    persistence = TaskPersistenceAdapter(tmp_path)
    for task_id, status in (("TASK-001", "running"), ("TASK-002", "pending")):
        persistence.save(_task(task_id, status))

    report = CrashRecoveryCoordinator(
        persistence,
        ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=2))),
    ).inspect(["TASK-002"])

    assert [d.task_id for d in report.decisions] == ["TASK-002"]
    assert report.recoverable_task_ids == ("TASK-002",)
    assert persistence.load("TASK-001").status == "running"
