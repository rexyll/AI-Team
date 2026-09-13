from __future__ import annotations

import pytest

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.task_manager import TaskManager


def _plan():
    return {
        "project": "demo",
        "summary": "demo project",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "architecture",
                "description": "design",
                "role": "architect",
                "dependencies": [],
            },
        ],
    }


class FakePlanner:
    def __init__(self, plan):
        self.plan = plan

    def run(self, task):
        return {"plan": self.plan}


class FakeRouter:
    def __init__(self, planner):
        self.planner = planner

    def get_agent(self, role):
        if role in ("analyst", "doc_writer"):
            return None
        assert role == "planner"
        return self.planner


class FakeOrchestrator:
    def __init__(self, task_manager, agent_router):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.run_called = False

    def run(self):
        self.run_called = True


def test_project_orchestrator_rejects_invalid_plan_at_project_boundary():
    invalid_plan = _plan()
    invalid_plan["tasks"][0]["dependencies"] = ["UNKNOWN"]

    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner(invalid_plan))
    )

    with pytest.raises(ValueError, match="unknown task"):
        project.create_plan("demo requirement")

    assert project.last_plan is None


def test_project_orchestrator_execute_is_explicit_project_execution_boundary():
    router = FakeRouter(FakePlanner(_plan()))
    captured = {}

    def factory(task_manager, agent_router):
        orchestrator = FakeOrchestrator(task_manager, agent_router)
        captured["orchestrator"] = orchestrator
        return orchestrator

    project = ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=factory,
    )
    manager = project.build_task_manager(_plan())

    result = project.execute(manager)

    assert isinstance(result, ProjectResult)
    assert result.success is False
    assert result.status == "incomplete"
    assert result.total_tasks == 1
    assert result.completed_tasks == 0
    assert result.failed_tasks == ()
    assert result.blocked_tasks == ()
    assert project.last_result is result
    assert captured["orchestrator"].run_called is True
    assert captured["orchestrator"].task_manager is manager


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
        "acceptance_verdict": None,
    }


def test_project_result_reports_failed_and_blocked_tasks():
    from runtime.task import Task

    manager = TaskManager(
        [
            Task(
                id="TASK-FAILED",
                title="failed",
                description="failed",
                role="developer",
                status="failed",
            ),
            Task(
                id="TASK-BLOCKED",
                title="blocked",
                description="blocked",
                role="tester",
                status="blocked",
            ),
        ]
    )

    result = ProjectResult.from_task_manager(manager)

    assert result.success is False
    assert result.status == "failed"
    assert result.total_tasks == 2
    assert result.completed_tasks == 0
    assert result.failed_tasks == ("TASK-FAILED",)
    assert result.blocked_tasks == ("TASK-BLOCKED",)


def test_project_result_requires_task_manager():
    with pytest.raises(TypeError, match="task_manager must be a TaskManager"):
        ProjectResult.from_task_manager(None)  # type: ignore[arg-type]


def test_project_orchestrator_execute_requires_task_manager():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner(_plan()))
    )

    with pytest.raises(TypeError, match="task_manager must be a TaskManager"):
        project.execute(None)
