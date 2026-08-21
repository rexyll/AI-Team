import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus, can_transition


def _manager(status: str = TaskStatus.PENDING.value) -> TaskManager:
    task = Task(
        id="WF-STATE-001",
        title="workflow state contract",
        description="workflow state machine contract test",
        role="developer",
        status=status,
    )
    return TaskManager([task])


def test_task_manager_is_the_single_transition_boundary():
    manager = _manager(TaskStatus.PENDING.value)
    task = manager.get_task("WF-STATE-001")

    assert task.status == TaskStatus.PENDING.value

    manager.transition(task.id, TaskStatus.READY)
    manager.transition(task.id, TaskStatus.RUNNING)

    assert task.status == TaskStatus.RUNNING.value
    assert task.status_history == [
        {"from": "pending", "to": "ready"},
        {"from": "ready", "to": "running"},
    ]


def test_workflow_happy_path_is_explicitly_legal():
    path = [
        TaskStatus.PENDING,
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.REVIEW_PENDING,
        TaskStatus.REVIEWING,
        TaskStatus.COMPLETED,
    ]

    assert all(
        can_transition(current, target)
        for current, target in zip(path, path[1:])
    )


def test_workflow_revision_path_returns_to_running():
    path = [
        TaskStatus.RUNNING,
        TaskStatus.REVIEW_PENDING,
        TaskStatus.REVIEWING,
        TaskStatus.REVISION,
        TaskStatus.RUNNING,
    ]

    assert all(
        can_transition(current, target)
        for current, target in zip(path, path[1:])
    )


def test_terminal_states_cannot_resume():
    for terminal in (
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    ):
        assert not can_transition(terminal, TaskStatus.RUNNING)
        assert not can_transition(terminal, TaskStatus.REVIEWING)


def test_illegal_workflow_jump_is_rejected():
    manager = _manager(TaskStatus.PENDING.value)

    with pytest.raises(ValueError, match="Invalid task status transition"):
        manager.transition("WF-STATE-001", TaskStatus.COMPLETED)


def test_transition_history_is_append_only_for_successful_transitions():
    manager = _manager(TaskStatus.PENDING.value)
    task = manager.get_task("WF-STATE-001")

    with pytest.raises(ValueError):
        manager.transition(task.id, TaskStatus.COMPLETED)

    assert task.status == TaskStatus.PENDING.value
    assert task.status_history == []
