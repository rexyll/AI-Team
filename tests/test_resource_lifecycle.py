from __future__ import annotations

from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.resource_lifecycle import ResourceLifecycle
from runtime.task import Task


def _task(task_id: str = "TASK-001") -> Task:
    return Task(id=task_id, title="task", description="task", role="developer")


def test_admit_consume_finish_accounts_resources():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1, max_tool_calls=5, max_input_tokens=100, max_output_tokens=100))
    lifecycle = ResourceLifecycle.admit(_task(), governor)
    assert lifecycle is not None
    assert lifecycle.active is True
    assert lifecycle.governor.usage.active_tasks == 1

    lifecycle = lifecycle.consume(tool_calls=2, input_tokens=10, output_tokens=7)
    assert lifecycle.governor.usage.tool_calls == 2
    assert lifecycle.governor.usage.input_tokens == 10
    assert lifecycle.governor.usage.output_tokens == 7

    finished = lifecycle.finish()
    assert finished.active is False
    assert finished.governor.usage.active_tasks == 0
    assert finished.governor.usage.tool_calls == 2


def test_admission_failure_returns_none_without_task_mutation():
    task = _task()
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    running = governor.start_task()

    assert ResourceLifecycle.admit(task, running) is None
    assert task.status == "pending"
    assert running.usage.active_tasks == 1


def test_finish_is_idempotent_and_does_not_double_release():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    lifecycle = ResourceLifecycle.admit(_task(), governor)
    first = lifecycle.finish()
    second = first.finish()

    assert first == second
    assert second.governor.usage.active_tasks == 0
