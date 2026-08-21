import threading
import time

from core.orchestrator import Orchestrator
from runtime.task import Task
from runtime.task_manager import TaskManager


class _ParallelAgent:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.finished = set()
        self.started = []

    def run(self, task):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.started.append(task.id)

        time.sleep(0.04)

        with self.lock:
            self.active -= 1
            self.finished.add(task.id)

        return {
            "status": "completed",
            "agent": task.role,
            "task_id": task.id,
            "message": "completed",
            "data": {},
        }


class _Router:
    def __init__(self, agent):
        self.agent = agent

    def get_agent(self, role):
        return self.agent


def _task(task_id, dependencies=None):
    return Task(
        id=task_id,
        title=task_id,
        description="parallel execution test",
        role="architect",
        dependencies=dependencies or [],
    )


def test_orchestrator_executes_independent_ready_tasks_concurrently():
    agent = _ParallelAgent()
    manager = TaskManager([
        _task("TASK-001"),
        _task("TASK-002"),
    ])

    Orchestrator(manager, _Router(agent), max_workers=2).run()

    assert agent.peak == 2
    assert {task.id for task in manager.get_all_tasks()} == {
        "TASK-001",
        "TASK-002",
    }
    assert all(task.status == "completed" for task in manager.get_all_tasks())


def test_orchestrator_waits_for_dependency_layer_before_next_layer():
    agent = _ParallelAgent()
    manager = TaskManager([
        _task("TASK-001"),
        _task("TASK-002"),
        _task("TASK-003", ["TASK-001", "TASK-002"]),
    ])

    Orchestrator(manager, _Router(agent), max_workers=2).run()

    assert agent.started[:2] == ["TASK-001", "TASK-002"]
    assert agent.started[2] == "TASK-003"
    assert all(task.status == "completed" for task in manager.get_all_tasks())


def test_orchestrator_parallel_failure_does_not_cancel_peer_task():
    class _FailureAgent(_ParallelAgent):
        def run(self, task):
            if task.id == "TASK-001":
                time.sleep(0.02)
                raise RuntimeError("intentional failure")
            return super().run(task)

    agent = _FailureAgent()
    manager = TaskManager([
        _task("TASK-001"),
        _task("TASK-002"),
        _task("TASK-003", ["TASK-001"]),
    ])

    Orchestrator(manager, _Router(agent), max_workers=2).run()

    assert manager.get_task("TASK-001").status == "failed"
    assert manager.get_task("TASK-002").status == "completed"
    assert manager.get_task("TASK-003").status == "blocked"
