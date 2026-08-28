from __future__ import annotations

import pytest

from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.resource_lifecycle import ResourceLifecycle
from runtime.task import Task


def _task(task_id: str) -> Task:
    return Task(id=task_id, title="task", description="task", role="developer")


def test_failed_execution_can_release_its_admission_slot():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    lifecycle = ResourceLifecycle.admit(_task("TASK-001"), governor)
    assert lifecycle is not None

    released = lifecycle.finish()

    assert released.active is False
    assert released.governor.usage.active_tasks == 0
    assert ResourceLifecycle.admit(_task("TASK-002"), released.governor) is not None


def test_budget_exhaustion_does_not_implicitly_release_or_mutate_snapshot():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1, max_tool_calls=1))
    lifecycle = ResourceLifecycle.admit(_task("TASK-001"), governor)
    assert lifecycle is not None

    with pytest.raises(RuntimeError, match="resource budget exceeded"):
        lifecycle.consume(tool_calls=2)

    assert lifecycle.active is True
    assert lifecycle.governor.usage.active_tasks == 1
    assert lifecycle.governor.usage.tool_calls == 0


def test_finish_after_partial_consumption_preserves_consumed_budget():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1, max_tool_calls=3))
    lifecycle = ResourceLifecycle.admit(_task("TASK-001"), governor)
    consumed = lifecycle.consume(tool_calls=2)

    finished = consumed.finish()

    assert finished.governor.usage.active_tasks == 0
    assert finished.governor.usage.tool_calls == 2
