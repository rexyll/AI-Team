import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


def make_manager(status):
    task = Task(
        id="TASK-001",
        title="test",
        description="test",
        role="developer",
        status=status,
    )

    return TaskManager([task]), task


@pytest.mark.parametrize(
    "current,target",
    [
        ("pending", "ready"),
        ("pending", "blocked"),
        ("ready", "running"),
        ("ready", "failed"),
        ("running", "review_pending"),
        ("running", "completed"),
        ("running", "failed"),
        ("review_pending", "running"),
        ("review_pending", "reviewing"),
        ("review_pending", "failed"),
        ("reviewing", "running"),
        ("reviewing", "completed"),
        ("reviewing", "failed"),
        ("blocked", "ready"),
    ],
)
def test_valid_task_transitions(current, target):
    manager, task = make_manager(current)

    manager.transition(
        task.id,
        target,
    )

    assert task.status == target
    
@pytest.mark.parametrize(
    "current,target",
    [
        ("completed", "running"),
        ("completed", "pending"),
        ("failed", "running"),
        ("failed", "ready"),
        ("reviewing", "ready"),
        ("pending", "running"),
    ],
)
def test_invalid_task_transitions(current, target):
    manager, task = make_manager(current)

    with pytest.raises(ValueError):
        manager.transition(
            task.id,
            target,
        )