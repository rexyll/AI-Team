from __future__ import annotations

from runtime.task import Task


def independent_implementation_tasks() -> list[Task]:
    """Independent implementation tasks followed by an integration task."""
    return [
        Task("ROOT", "Root", "benchmark root", "developer", status="completed"),
        Task("TASK-A", "Utility A", "implement utility A", "developer", dependencies=["ROOT"]),
        Task("TASK-B", "Utility B", "implement utility B", "developer", dependencies=["ROOT"]),
        Task("TASK-C", "Utility C", "implement utility C", "developer", dependencies=["ROOT"]),
        Task("FINAL", "Integration", "integrate utilities", "developer", dependencies=["TASK-A", "TASK-B", "TASK-C"]),
    ]


def partial_implementation_tasks() -> list[Task]:
    """Two implementation branches plus one independent task converge at integration."""
    return [
        Task("ROOT", "Root", "benchmark root", "developer", status="completed"),
        Task("TASK-A", "Utility A", "implement utility A", "developer", dependencies=["ROOT"]),
        Task("TASK-B", "Utility B", "implement utility B", "developer", dependencies=["ROOT"]),
        Task("TASK-C", "Utility C", "implement utility C", "developer", dependencies=["ROOT"]),
        Task("FINAL", "Integration", "integrate utilities", "developer", dependencies=["TASK-A", "TASK-B", "TASK-C"]),
    ]


def serial_implementation_tasks() -> list[Task]:
    """A controlled serial implementation chain."""
    return [
        Task("TASK-1", "Utility 1", "implement utility 1", "developer"),
        Task("TASK-2", "Utility 2", "implement utility 2", "developer", dependencies=["TASK-1"]),
        Task("TASK-3", "Utility 3", "implement utility 3", "developer", dependencies=["TASK-2"]),
        Task("TASK-4", "Integration", "integrate utility 3", "developer", dependencies=["TASK-3"]),
    ]
