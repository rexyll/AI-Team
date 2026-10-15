import pytest

from runtime.cancellation import CancellationRequested
from runtime.dependency_scheduler import DependencyScheduler
from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus


def _task(task_id: str = "TASK-001") -> Task:
    return Task(
        id=task_id,
        title="task",
        description="test",
        role="developer",
    )


def test_task_cancellation_is_terminal_and_not_a_failure():
    task = _task()

    snapshot = task.cancel("operator stopped task")

    assert snapshot.requested is True
    assert snapshot.reason == "operator stopped task"
    assert task.status == TaskStatus.CANCELLED.value
    assert task.error is None
    assert task.retry_attempt == 0
    assert task.retry_history == []


def test_cancel_is_idempotent_and_preserves_first_reason():
    task = _task()

    first = task.cancel("first reason")
    second = task.cancel("later reason")

    assert second == first
    assert task.status == TaskStatus.CANCELLED.value


def test_cancelled_task_is_not_ready_or_runnable():
    task = _task()
    task.cancel("operator stopped task")
    scheduler = DependencyScheduler([task])

    assert scheduler.get_ready_tasks() == []
    decision = scheduler.decision_for(task.id)
    assert decision.runnable is False
    assert decision.blocked is False
    assert decision.reason == "Task is cancelled"


def test_cancelled_task_cannot_be_admitted():
    task = _task()
    task.cancel("operator stopped task")
    coordinator = ResourceExecutionCoordinator(
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    )

    assert coordinator.admit(task) is None
    assert coordinator.governor.usage.active_tasks == 0
    assert coordinator.active_task_ids == ()


def test_running_cancelled_task_releases_resource_once():
    task = _task()
    coordinator = ResourceExecutionCoordinator(
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    )

    lifecycle = coordinator.admit(task)
    assert lifecycle is not None
    assert coordinator.governor.usage.active_tasks == 1

    task.cancel("operator stopped task")
    coordinator.cancel(task.id)

    assert coordinator.governor.usage.active_tasks == 0
    assert coordinator.active_task_ids == ()
    assert coordinator.cancel(task.id).usage.active_tasks == 0


def test_task_cancellation_raises_through_token():
    task = _task()
    task.cancel("operator stopped task")

    with pytest.raises(CancellationRequested, match="operator stopped task"):
        task.raise_if_cancelled()


def test_task_cancellation_round_trip_persists():
    task = _task()
    task.cancel("operator stopped task")

    restored = Task.from_dict(task.to_dict())

    assert restored.status == TaskStatus.CANCELLED.value
    assert restored.cancellation_requested is True
    assert restored.cancellation_reason == "operator stopped task"
    with pytest.raises(CancellationRequested, match="operator stopped task"):
        restored.raise_if_cancelled()
