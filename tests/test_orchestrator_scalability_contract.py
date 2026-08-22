from __future__ import annotations

from threading import Lock

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager


TASK_COUNT = 512
MAX_WORKERS = 4


class ScalableReviewer:
    role = "reviewer"

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self._lock = Lock()
        self.active = 0
        self.max_active = 0

    def run(self, task: Task) -> dict:
        with self._lock:
            self.calls[task.id] = self.calls.get(task.id, 0) + 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return {
                "status": "completed",
                "agent": "reviewer",
                "task_id": task.id,
            }
        finally:
            with self._lock:
                self.active -= 1


def _manager(count: int = TASK_COUNT) -> TaskManager:
    return TaskManager(
        [
            Task(
                id=f"TASK-SCALE-{index:04d}",
                title=f"scheduler scalability {index}",
                description="exercise large ready-task scheduling",
                role="reviewer",
            )
            for index in range(count)
        ]
    )


def test_scheduler_scales_large_ready_set_without_duplicate_or_missing_dispatch():
    manager = _manager()
    reviewer = ScalableReviewer()
    router = AgentRouter()
    router.register("reviewer", reviewer)

    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=router,
        max_workers=MAX_WORKERS,
    )
    orchestrator.run()

    tasks = manager.get_all_tasks()
    assert len(tasks) == TASK_COUNT
    assert all(task.status == "completed" for task in tasks)
    assert len(reviewer.calls) == TASK_COUNT
    assert all(call_count == 1 for call_count in reviewer.calls.values())
    assert reviewer.max_active <= MAX_WORKERS


def test_scheduler_preserves_dependency_order_at_scale():
    root = Task(
        id="TASK-SCALE-ROOT",
        title="root",
        description="dependency root",
        role="reviewer",
    )
    children = [
        Task(
            id=f"TASK-SCALE-CHILD-{index:04d}",
            title=f"child {index}",
            description="dependent ready task",
            role="reviewer",
            dependencies=[root.id],
        )
        for index in range(TASK_COUNT - 1)
    ]
    manager = TaskManager([root, *children])
    reviewer = ScalableReviewer()
    router = AgentRouter()
    router.register("reviewer", reviewer)

    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=router,
        max_workers=MAX_WORKERS,
    )
    orchestrator.run()

    assert root.status == "completed"
    assert all(task.status == "completed" for task in children)
    assert reviewer.calls[root.id] == 1
    assert all(reviewer.calls[task.id] == 1 for task in children)
