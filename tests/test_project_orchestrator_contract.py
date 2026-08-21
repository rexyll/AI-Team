from __future__ import annotations

import pytest

from core.project_orchestrator import ProjectOrchestrator
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

    assert result is manager
    assert captured["orchestrator"].run_called is True
    assert captured["orchestrator"].task_manager is manager


def test_project_orchestrator_execute_requires_task_manager():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner(_plan()))
    )

    with pytest.raises(TypeError, match="task_manager must be a TaskManager"):
        project.execute(None)
