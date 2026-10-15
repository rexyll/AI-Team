from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.timeout import TimeoutController
from runtime.timeout_execution import TimeoutExecutionController


def _task(task_id="TASK-001"):
    return Task(id=task_id, title="test", description="test", role="developer")


def test_timeout_cancels_task_without_failure_or_retry():
    task = _task()
    resources = ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)))
    lifecycle = resources.admit(task)
    assert lifecycle is not None

    now = [10.0]
    timeout = TimeoutController(5, token=task._cancellation_token, clock=lambda: now[0])
    controller = TimeoutExecutionController(resources)

    now[0] = 15.0
    decision = controller.check(task, timeout)

    assert decision.timed_out is True
    assert decision.cancelled is True
    assert decision.retryable is False
    assert task.status == TaskStatus.CANCELLED.value
    assert task.error is None
    assert task.retry_attempt == 0
    assert resources.governor.usage.active_tasks == 0


def test_timeout_release_is_idempotent():
    task = _task()
    resources = ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)))
    assert resources.admit(task) is not None

    now = [0.0]
    timeout = TimeoutController(1, token=task._cancellation_token, clock=lambda: now[0])
    controller = TimeoutExecutionController(resources)
    now[0] = 1.0

    first = controller.check(task, timeout)
    second = controller.check(task, timeout)

    assert first.timed_out is True
    assert second.timed_out is True
    assert resources.governor.usage.active_tasks == 0
    assert resources.active_task_ids == ()


def test_operator_cancellation_reason_is_preserved_when_timeout_follows():
    task = _task()
    resources = ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)))
    assert resources.admit(task) is not None
    task.cancel("operator requested cancellation")

    now = [2.0]
    timeout = TimeoutController(1, token=task._cancellation_token, clock=lambda: now[0])
    controller = TimeoutExecutionController(resources)
    now[0] = 3.0

    decision = controller.check(task, timeout)

    assert decision.timed_out is True
    assert decision.reason == "operator requested cancellation"
    assert task.cancellation_reason == "operator requested cancellation"
    assert resources.governor.usage.active_tasks == 0
