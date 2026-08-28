from __future__ import annotations

from runtime.resource_governor import ResourceGovernor, ResourceLimits


def test_resource_rejection_is_non_mutating():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))
    admitted = governor.start_task()
    assert admitted.usage.active_tasks == 1

    assert not admitted.can_start_task()
    assert admitted.usage.active_tasks == 1


def test_finish_releases_capacity_without_affecting_budget_counters():
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1, max_tool_calls=3))
    running = governor.start_task()
    consumed = running.consume(tool_calls=2)

    released = consumed.finish_task()

    assert released.usage.active_tasks == 0
    assert released.usage.tool_calls == 2


def test_tool_and_token_rejection_preserves_previous_snapshot():
    governor = ResourceGovernor(ResourceLimits(max_tool_calls=2, max_input_tokens=10, max_output_tokens=10))
    used = governor.consume(tool_calls=1, input_tokens=4, output_tokens=3)

    assert not used.can_consume(tool_calls=2)
    assert not used.can_consume(input_tokens=7)
    assert not used.can_consume(output_tokens=8)
    assert used.usage.tool_calls == 1
    assert used.usage.input_tokens == 4
    assert used.usage.output_tokens == 3
