import pytest

from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_status import TaskStatus
from runtime.timeout import TimeoutController
from runtime.timeout_execution import TimeoutExecutionController
from runtime.timeout_recovery import decide_timeout_recovery, timeout_exception_is_control_plane


def _task(task_id="TASK-001"):
    return Task(id=task_id, title="test", description="test", role="developer")


def _timed_out_task():
    task = _task()
    resources = ResourceExecutionCoordinator(ResourceGovernor(ResourceLimits(max_concurrent_tasks=1)))
    assert resources.admit(task) is not None
    now = [0.0]
    timeout = TimeoutController(1, token=task._cancellation_token, clock=lambda: now[0])
    now[0] = 1.0
    TimeoutExecutionController(resources).check(task, timeout)
    return task


def test_timeout_recovery_default_is_noop_and_does_not_mutate_task():
    task = _timed_out_task()
    before = task.to_dict()

    decision = decide_timeout_recovery(task)

    assert decision.action == "none"
    assert task.to_dict() == before
    assert task.status == TaskStatus.CANCELLED.value
    assert task.retry_attempt == 0


def test_timeout_retry_is_explicit_and_does_not_increment_retry_counter():
    task = _timed_out_task()
    task.configure_retry(max_retries=2)

    decision = decide_timeout_recovery(task, action="retry", reason="operator-approved retry")

    assert decision.action == "retry"
    assert decision.reason == "operator-approved retry"
    assert task.retry_attempt == 0
    assert task.status == TaskStatus.CANCELLED.value


def test_timeout_recovery_rejects_implicit_retry_when_budget_is_exhausted():
    task = _timed_out_task()
    task.configure_retry(max_retries=0)

    with pytest.raises(ValueError, match="retry budget"):
        decide_timeout_recovery(task, action="retry")


def test_timeout_recovery_requires_cancelled_task():
    task = _task()
    with pytest.raises(ValueError, match="cancelled task"):
        decide_timeout_recovery(task, action="recover")


def test_timeout_exception_is_control_plane_signal():
    from runtime.timeout import TimeoutExceeded

    assert timeout_exception_is_control_plane(TimeoutExceeded("expired")) is True
    assert timeout_exception_is_control_plane(RuntimeError("failure")) is False
