from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task


def _task(task_id: str) -> Task:
    return Task(id=task_id, title=task_id, description=task_id, role="developer")


def test_admission_reserves_slots_and_rejection_is_non_mutating():
    coordinator = ResourceExecutionCoordinator(
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=2))
    )

    first = coordinator.admit(_task("TASK-001"))
    second = coordinator.admit(_task("TASK-002"))
    rejected = coordinator.admit(_task("TASK-003"))

    assert first is not None
    assert second is not None
    assert rejected is None
    assert coordinator.governor.usage.active_tasks == 2
    assert coordinator.active_task_ids == ("TASK-001", "TASK-002")


def test_out_of_order_finish_never_under_counts_active_tasks():
    coordinator = ResourceExecutionCoordinator(
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=2))
    )
    assert coordinator.admit(_task("TASK-001")) is not None
    assert coordinator.admit(_task("TASK-002")) is not None

    coordinator.finish("TASK-001")
    assert coordinator.governor.usage.active_tasks == 1
    assert coordinator.is_active("TASK-002")

    coordinator.finish("TASK-002")
    assert coordinator.governor.usage.active_tasks == 0
    assert coordinator.active_task_ids == ()


def test_concurrent_admission_never_exceeds_limit():
    coordinator = ResourceExecutionCoordinator(
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=4))
    )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(
            coordinator.admit,
            [_task(f"TASK-{index:02d}") for index in range(16)],
        ))

    assert sum(result is not None for result in results) == 4
    assert coordinator.governor.usage.active_tasks == 4

    for task_id in coordinator.active_task_ids:
        coordinator.finish(task_id)
    assert coordinator.governor.usage.active_tasks == 0
