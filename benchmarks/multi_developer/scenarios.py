from __future__ import annotations

from runtime.task import Task


def fully_parallel_tasks() -> list[Task]:
    """One dependency followed by four independent tasks."""
    return [
        Task("ROOT", "Root", "root", "developer", status="completed"),
        Task("TASK-1", "Task 1", "parallel 1", "developer", dependencies=["ROOT"]),
        Task("TASK-2", "Task 2", "parallel 2", "developer", dependencies=["ROOT"]),
        Task("TASK-3", "Task 3", "parallel 3", "developer", dependencies=["ROOT"]),
        Task("TASK-4", "Task 4", "parallel 4", "developer", dependencies=["ROOT"]),
    ]


def partially_parallel_tasks() -> list[Task]:
    """Two parallel branches converge into one final task."""
    return [
        Task("ROOT", "Root", "root", "developer", status="completed"),
        Task("TASK-A", "Task A", "branch A", "developer", dependencies=["ROOT"]),
        Task("TASK-B", "Task B", "branch B", "developer", dependencies=["ROOT"]),
        Task("TASK-C", "Task C", "branch C", "developer", dependencies=["ROOT"]),
        Task("FINAL", "Final", "convergence", "developer", dependencies=["TASK-A", "TASK-B", "TASK-C"]),
    ]


def serial_tasks() -> list[Task]:
    """A dependency chain where additional Developers should add little value."""
    return [
        Task("TASK-1", "Task 1", "serial 1", "developer"),
        Task("TASK-2", "Task 2", "serial 2", "developer", dependencies=["TASK-1"]),
        Task("TASK-3", "Task 3", "serial 3", "developer", dependencies=["TASK-2"]),
        Task("TASK-4", "Task 4", "serial 4", "developer", dependencies=["TASK-3"]),
        Task("TASK-5", "Task 5", "serial 5", "developer", dependencies=["TASK-4"]),
    ]
