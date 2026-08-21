from dataclasses import FrozenInstanceError

import pytest

from core.project_result import ProjectResult
from runtime.task import Task
from runtime.task_manager import TaskManager


def _task(task_id: str, status: str) -> Task:
    return Task(
        id=task_id,
        title=task_id,
        description="project result contract",
        role="architect",
        status=status,
    )


def test_project_result_is_immutable_value_object():
    result = ProjectResult(
        project="demo",
        success=True,
        status="completed",
        total_tasks=1,
        completed_tasks=1,
        failed_tasks=(),
        blocked_tasks=(),
    )

    with pytest.raises(FrozenInstanceError):
        result.status = "failed"


def test_project_result_from_empty_task_manager_is_incomplete():
    result = ProjectResult.from_task_manager(TaskManager([]), project="empty")

    assert result.project == "empty"
    assert result.success is False
    assert result.status == "incomplete"
    assert result.total_tasks == 0
    assert result.completed_tasks == 0
    assert result.failed_tasks == ()
    assert result.blocked_tasks == ()


def test_project_result_summarizes_successful_tasks():
    manager = TaskManager([
        _task("TASK-001", "completed"),
        _task("TASK-002", "completed"),
    ])

    result = ProjectResult.from_task_manager(manager, project="demo")

    assert result == ProjectResult(
        project="demo",
        success=True,
        status="completed",
        total_tasks=2,
        completed_tasks=2,
        failed_tasks=(),
        blocked_tasks=(),
    )


def test_project_result_summarizes_failed_tasks():
    manager = TaskManager([
        _task("TASK-001", "completed"),
        _task("TASK-002", "failed"),
    ])

    result = ProjectResult.from_task_manager(manager)

    assert result.success is False
    assert result.status == "failed"
    assert result.total_tasks == 2
    assert result.completed_tasks == 1
    assert result.failed_tasks == ("TASK-002",)
    assert result.blocked_tasks == ()


def test_project_result_summarizes_blocked_tasks():
    manager = TaskManager([
        _task("TASK-001", "completed"),
        _task("TASK-002", "blocked"),
    ])

    result = ProjectResult.from_task_manager(manager)

    assert result.success is False
    assert result.status == "failed"
    assert result.failed_tasks == ()
    assert result.blocked_tasks == ("TASK-002",)


def test_project_result_to_dict_is_json_friendly():
    manager = TaskManager([
        _task("TASK-001", "completed"),
        _task("TASK-002", "failed"),
        _task("TASK-003", "blocked"),
    ])

    result = ProjectResult.from_task_manager(manager, project="demo")

    assert result.to_dict() == {
        "project": "demo",
        "success": False,
        "status": "failed",
        "total_tasks": 3,
        "completed_tasks": 1,
        "failed_tasks": ["TASK-002"],
        "blocked_tasks": ["TASK-003"],
    }


def test_project_result_does_not_retain_task_manager_reference():
    manager = TaskManager([_task("TASK-001", "completed")])
    result = ProjectResult.from_task_manager(manager)

    assert all(
        not hasattr(result, field)
        for field in ("task_manager", "agent", "llm", "provider")
    )


def test_project_result_rejects_non_task_manager_source():
    with pytest.raises(TypeError, match="task_manager must be a TaskManager"):
        ProjectResult.from_task_manager(object())
