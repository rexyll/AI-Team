import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager


def test_pending_task_can_become_executable():
    task = Task(
        id="TASK-EXEC-001",
        title="execution gate",
        description="test execution gate",
        role="developer",
        status="pending",
    )

    manager = TaskManager([task])

    # 根据你当前依赖规则，
    # 无依赖 pending 应该可以进入 ready。
    manager.get_ready_tasks()

    assert task.status == "ready"
    
def test_completed_task_cannot_be_executed():
    task = Task(
        id="TASK-EXEC-002",
        title="completed",
        description="completed task",
        role="developer",
        status="completed",
    )

    manager = TaskManager([task])

    with pytest.raises(ValueError):
        manager.ensure_executable(task.id)
        
def test_failed_task_cannot_be_executed():
    task = Task(
        id="TASK-EXEC-003",
        title="failed",
        description="failed task",
        role="developer",
        status="failed",
    )

    manager = TaskManager([task])

    with pytest.raises(ValueError):
        manager.ensure_executable(task.id)
        
        
def test_blocked_task_cannot_be_executed():
    task = Task(
        id="TASK-EXEC-004",
        title="blocked",
        description="blocked task",
        role="developer",
        status="blocked",
    )

    manager = TaskManager([task])

    with pytest.raises(ValueError):
        manager.ensure_executable(task.id)
        
def test_running_task_is_executable():
    task = Task(
        id="TASK-EXEC-005",
        title="running",
        description="running task",
        role="developer",
        status="running",
    )

    manager = TaskManager([task])

    result = manager.ensure_executable(task.id)

    assert result is task
    assert task.status == "running"