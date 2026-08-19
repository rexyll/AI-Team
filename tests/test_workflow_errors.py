import pytest

from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class FailingDeveloper:
    def run(self, task):
        raise RuntimeError("developer boom")


class FailingReviewer:
    def run(self, task):
        raise RuntimeError("reviewer boom")


class SuccessfulDeveloper:
    def run(self, task):
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "ok",
        }


def _workflow(task, developer, reviewer):
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    manager = TaskManager([task])
    return manager, TaskWorkflow(
        manager,
        developer,
        reviewer,
        router,
    )


def test_developer_failure_marks_task_failed():
    task = Task("FAIL-DEV", "x", "x", "developer", status="ready")
    manager, workflow = _workflow(task, FailingDeveloper(), FailingReviewer())

    with pytest.raises(RuntimeError, match="developer boom"):
        workflow.execute(task.id)

    assert task.status == "failed"
    assert "Developer execution failed" in task.error


def test_reviewer_failure_marks_review_task_failed():
    task = Task("FAIL-REVIEW", "x", "x", "developer", status="ready")
    manager, workflow = _workflow(task, SuccessfulDeveloper(), FailingReviewer())

    with pytest.raises(RuntimeError, match="reviewer boom"):
        workflow.execute(task.id)

    assert task.status == "failed"
    assert "Reviewer execution failed" in task.error
