from core.project_result import ProjectResult
from runtime.project_orchestrator import ProjectOrchestrator
from runtime.task_manager import TaskManager


def test_project_result_reports_successful_execution():
    manager = TaskManager([])
    manager.tasks = {}

    # A one-task completed manager is enough to validate the project-level
    # result contract without invoking an LLM or the workflow runtime.
    from runtime.task import Task

    manager = TaskManager(
        [
            Task(
                id="TASK-001",
                title="done",
                description="done",
                role="architect",
                status="completed",
            )
        ]
    )

    result = ProjectResult.from_task_manager(manager, project="demo")

    assert result.to_dict() == {
        "project": "demo",
        "success": True,
        "status": "completed",
        "total_tasks": 1,
        "completed_tasks": 1,
        "failed_tasks": [],
        "blocked_tasks": [],
        "completed_task_ids": ["TASK-001"],
    }
