from __future__ import annotations

from runtime.resource_admission import admit_task
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task


def _task(task_id: str = "TASK-001") -> Task:
    return Task(id=task_id, title="task", description="task", role="developer")


def test_admission_success_is_read_only_for_task():
    task = _task()
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))

    decision = admit_task(task, governor)

    assert decision.admitted is True
    assert decision.task_id == task.id
    assert task.status == "pending"
    assert governor.usage.active_tasks == 0


def test_resource_rejection_is_not_a_task_failure():
    task = _task()
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    running = governor.start_task()
    assert running is not None

    decision = admit_task(task, running)

    assert decision.admitted is False
    assert decision.reason == "Resource limit reached: max_concurrent_tasks"
    assert task.status == "pending"
    assert running.usage.active_tasks == 1
