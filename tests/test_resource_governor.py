from __future__ import annotations

import pytest

from runtime.resource_governor import ResourceGovernor, ResourceLimits, ResourceUsage


def test_concurrency_limit_is_hard_and_immutable():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=2))
    running = governor.start_task().start_task()

    assert running.usage.active_tasks == 2
    assert not running.can_start_task()
    with pytest.raises(RuntimeError, match="concurrency resource limit"):
        running.start_task()
    assert governor.usage.active_tasks == 0


def test_finish_task_releases_only_active_capacity():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=2))
    running = governor.start_task().start_task().finish_task()

    assert running.usage.active_tasks == 1
    assert running.can_start_task()


def test_budget_counters_are_monotonic_and_hard_limited():
    governor = ResourceGovernor(
        ResourceLimits(max_concurrent_tasks=2, max_tool_calls=3, max_input_tokens=100, max_output_tokens=50)
    )
    consumed = governor.consume(tool_calls=2, input_tokens=40, output_tokens=10)

    assert consumed.usage.tool_calls == 2
    assert consumed.can_consume(tool_calls=1, input_tokens=60, output_tokens=40)
    assert not consumed.can_consume(tool_calls=2)
    assert not consumed.can_consume(input_tokens=61)
    assert not consumed.can_consume(output_tokens=41)


def test_consume_rejects_budget_overrun_without_mutating_previous_snapshot():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1, max_tool_calls=1))
    with pytest.raises(RuntimeError, match="resource budget"):
        governor.consume(tool_calls=2)

    assert governor.usage == ResourceUsage()


def test_usage_snapshot_is_not_mutable_through_governor():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    assert governor.usage == ResourceUsage()
    updated = governor.start_task()

    assert governor.usage.active_tasks == 0
    assert updated.usage.active_tasks == 1


def test_limits_validate_values():
    with pytest.raises(ValueError):
        ResourceLimits(max_concurrent_tasks=0)
    with pytest.raises(ValueError):
        ResourceLimits(max_tool_calls=-1)
    with pytest.raises(TypeError):
        ResourceLimits(max_input_tokens=True)
