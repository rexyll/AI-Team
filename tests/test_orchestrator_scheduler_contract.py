from core.orchestrator import Orchestrator
from runtime.task import Task
from runtime.task_manager import TaskManager


class _Agent:
    def run(self, task):
        return {
            "status": "completed",
            "agent": task.role,
            "task_id": task.id,
            "message": "completed",
            "data": {},
        }


class _Router:
    def get_agent(self, role):
        return _Agent()


def _task(task_id, dependencies=None, status="pending"):
    return Task(
        id=task_id,
        title=task_id,
        description="scheduler boundary test",
        role="architect",
        dependencies=dependencies or [],
        status=status,
    )


def test_orchestrator_uses_scheduler_to_promote_ready_tasks():
    manager = TaskManager([
        _task("TASK-001"),
        _task("TASK-002", ["TASK-001"]),
    ])
    orchestrator = Orchestrator(manager, _Router())

    ready = orchestrator._get_executable_tasks()

    assert [task.id for task in ready] == ["TASK-001"]
    assert manager.get_task("TASK-001").status == "ready"
    assert manager.get_task("TASK-002").status == "pending"


def test_orchestrator_applies_scheduler_blocked_decision_through_task_manager():
    manager = TaskManager([
        _task("TASK-001", status="failed"),
        _task("TASK-002", ["TASK-001"]),
    ])
    orchestrator = Orchestrator(manager, _Router())

    ready = orchestrator._get_executable_tasks()

    assert ready == []
    assert manager.get_task("TASK-002").status == "blocked"
    assert "TASK-001" in manager.get_task("TASK-002").error


def test_orchestrator_does_not_directly_mutate_task_status():
    manager = TaskManager([
        _task("TASK-001"),
    ])
    orchestrator = Orchestrator(manager, _Router())
    task = manager.get_task("TASK-001")

    assert task.status == "pending"
    orchestrator._get_executable_tasks()

    assert task.status_history == [
        {"from": "pending", "to": "ready"},
    ]
