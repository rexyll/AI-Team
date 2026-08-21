import pytest

from runtime.dependency_scheduler import DependencyScheduler
from runtime.task import Task


def _task(task_id, dependencies=None, status="pending"):
    return Task(
        id=task_id,
        title=task_id,
        description="scheduler test",
        role="developer",
        dependencies=dependencies or [],
        status=status,
    )


def test_scheduler_returns_only_dependency_ready_tasks():
    tasks = [
        _task("TASK-001", status="completed"),
        _task("TASK-002", ["TASK-001"]),
        _task("TASK-003", ["TASK-002"]),
    ]

    scheduler = DependencyScheduler(tasks)

    assert [task.id for task in scheduler.get_ready_tasks()] == ["TASK-002"]


def test_scheduler_returns_independent_ready_tasks_deterministically():
    tasks = [
        _task("TASK-001"),
        _task("TASK-002"),
        _task("TASK-003", ["TASK-001"]),
    ]

    scheduler = DependencyScheduler(tasks)

    assert [task.id for task in scheduler.get_ready_tasks()] == [
        "TASK-001",
        "TASK-002",
    ]


def test_scheduler_reports_failed_dependency_as_blocked_without_mutation():
    task = _task("TASK-002", ["TASK-001"])
    tasks = [
        _task("TASK-001", status="failed"),
        task,
    ]
    before = (task.status, list(task.status_history), task.error)

    scheduler = DependencyScheduler(tasks)
    decision = scheduler.decision_for("TASK-002")

    assert decision.runnable is False
    assert decision.blocked is True
    assert "TASK-001" in decision.reason
    assert (task.status, task.status_history, task.error) == before


def test_scheduler_exposes_dependency_execution_layers():
    tasks = [
        _task("TASK-001"),
        _task("TASK-002", ["TASK-001"]),
        _task("TASK-003", ["TASK-001"]),
        _task("TASK-004", ["TASK-002", "TASK-003"]),
    ]

    scheduler = DependencyScheduler(tasks)

    assert scheduler.get_execution_layers() == [
        ["TASK-001"],
        ["TASK-002", "TASK-003"],
        ["TASK-004"],
    ]


def test_scheduler_rejects_unknown_dependency():
    with pytest.raises(ValueError, match="unknown task"):
        DependencyScheduler([_task("TASK-001", ["TASK-MISSING"])])


def test_scheduler_rejects_dependency_cycle():
    with pytest.raises(ValueError, match="Circular task dependency"):
        DependencyScheduler([
            _task("TASK-001", ["TASK-002"]),
            _task("TASK-002", ["TASK-001"]),
        ])


def test_scheduler_unknown_task_is_rejected():
    scheduler = DependencyScheduler([_task("TASK-001")])

    with pytest.raises(KeyError, match="Unknown task id"):
        scheduler.decision_for("TASK-MISSING")


def test_scheduler_is_read_only():
    tasks = [
        _task("TASK-001"),
        _task("TASK-002", ["TASK-001"]),
    ]
    before = [
        (task.status, list(task.status_history), task.error)
        for task in tasks
    ]

    scheduler = DependencyScheduler(tasks)
    scheduler.get_ready_tasks()
    scheduler.get_blocked_decisions()
    scheduler.get_execution_layers()

    after = [
        (task.status, list(task.status_history), task.error)
        for task in tasks
    ]

    assert after == before
