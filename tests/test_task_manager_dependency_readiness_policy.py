from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


def test_default_dependency_readiness_still_requires_completed():
    manager = TaskManager([
        Task("A", "A", "a", "developer", status=TaskStatus.REVIEW_PENDING.value),
        Task("B", "B", "b", "developer", dependencies=["A"]),
    ])

    assert manager.get_ready_tasks() == []
    assert manager.get_task("B").status == TaskStatus.PENDING.value


def test_dependency_readiness_can_treat_review_pending_as_satisfied():
    manager = TaskManager([
        Task("A", "A", "a", "developer", status=TaskStatus.REVIEW_PENDING.value),
        Task("B", "B", "b", "developer", dependencies=["A"]),
    ])

    ready = manager.get_ready_tasks(
        dependency_satisfied_statuses={
            TaskStatus.COMPLETED.value,
            TaskStatus.REVIEW_PENDING.value,
        }
    )

    assert [task.id for task in ready] == ["B"]
    assert manager.get_task("B").status == TaskStatus.READY.value
