from __future__ import annotations

import time

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task
from runtime.task_manager import TaskManager


class _TrackingReviewer:
    role = "reviewer"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def run(self, task):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.01)
            if self.fail:
                raise RuntimeError("review execution failed")
            return {
                "status": "approved",
                "agent": "reviewer",
                "task_id": task.id,
                "message": "APPROVED",
            }
        finally:
            self.active -= 1


def _router(reviewer: _TrackingReviewer) -> AgentRouter:
    router = AgentRouter()
    router.register("reviewer", reviewer)
    return router


def test_orchestrator_releases_resource_slot_after_success():
    reviewer = _TrackingReviewer()
    task = Task(id="TASK-001", title="review", description="review", role="reviewer", status="ready")
    manager = TaskManager([task])
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))

    orchestrator = Orchestrator(manager, _router(reviewer), resource_governor=governor)
    orchestrator.run()

    assert task.status == "completed"
    assert reviewer.calls == 1
    assert orchestrator.resource_governor.usage.active_tasks == 0


def test_orchestrator_releases_resource_slot_after_exception():
    reviewer = _TrackingReviewer(fail=True)
    task = Task(id="TASK-001", title="review", description="review", role="reviewer", status="ready")
    manager = TaskManager([task])
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))

    orchestrator = Orchestrator(manager, _router(reviewer), resource_governor=governor)
    orchestrator.run()

    assert task.status == "failed"
    assert orchestrator.resource_governor.usage.active_tasks == 0


def test_orchestrator_admission_limit_bounds_parallel_execution():
    reviewer = _TrackingReviewer()
    tasks = [
        Task(id=f"TASK-{index}", title="review", description="review", role="reviewer", status="ready")
        for index in range(4)
    ]
    manager = TaskManager(tasks)
    governor = ResourceGovernor(ResourceLimits(max_concurrent_tasks=1))

    orchestrator = Orchestrator(manager, _router(reviewer), max_workers=4, resource_governor=governor)
    orchestrator.run()

    assert all(task.status == "completed" for task in tasks)
    assert reviewer.calls == 4
    assert reviewer.max_active == 1
    assert orchestrator.resource_governor.usage.active_tasks == 0
