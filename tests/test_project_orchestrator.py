from __future__ import annotations

import pytest

from core.project_orchestrator import ProjectOrchestrator
from runtime.task_manager import TaskManager


def _plan():
    return {
        "project": "记账软件",
        "summary": "实现一个简单的个人记账软件。",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "数据库 Schema 设计",
                "description": "设计 SQLite 数据库结构。",
                "role": "architect",
                "dependencies": [],
            },
            {
                "id": "TASK-002",
                "title": "数据模型与 DAO 开发",
                "description": "根据数据库设计实现数据模型和 DAO。",
                "role": "developer",
                "dependencies": ["TASK-001"],
            },
            {
                "id": "TASK-003",
                "title": "测试",
                "description": "验证数据模型和 DAO 功能。",
                "role": "tester",
                "dependencies": ["TASK-002"],
            },
        ],
    }


class FakePlanner:
    role = "planner"

    def __init__(self, plan=None):
        self.plan = plan if plan is not None else _plan()
        self.received_task = None

    def run(self, task):
        self.received_task = task

        return {
            "status": "planner_completed",
            "agent": "planner",
            "task_id": task.id,
            "plan": self.plan,
        }


class FailingPlanner:
    role = "planner"

    def run(self, task):
        raise RuntimeError("planner failed")


class InvalidPlannerResult:
    role = "planner"

    def run(self, task):
        return {
            "status": "planner_completed",
            "agent": "planner",
            "task_id": task.id,
        }


class FakeRouter:
    def __init__(self, planner):
        self.planner = planner

    def get_agent(self, role):
        if role == "planner":
            return self.planner

        raise KeyError(role)


class FakeOrchestrator:
    def __init__(self, task_manager, agent_router):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.run_called = False

    def run(self):
        self.run_called = True


def test_create_plan_calls_planner():
    planner = FakePlanner()
    router = FakeRouter(planner)

    project = ProjectOrchestrator(
        agent_router=router,
    )

    plan = project.create_plan(
        "开发一个个人记账软件。"
    )

    assert plan == _plan()

    assert planner.received_task is not None
    assert planner.received_task.id == "PLAN-001"
    assert planner.received_task.role == "planner"
    assert planner.received_task.status == "ready"
    assert (
        planner.received_task.description
        == "开发一个个人记账软件。"
    )


def test_create_plan_stores_last_plan():
    planner = FakePlanner()
    router = FakeRouter(planner)

    project = ProjectOrchestrator(
        agent_router=router,
    )

    plan = project.create_plan(
        "开发一个个人记账软件。"
    )

    assert project.last_plan is plan


def test_create_plan_rejects_empty_requirement():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner()),
    )

    with pytest.raises(ValueError):
        project.create_plan("")


def test_create_plan_rejects_whitespace_requirement():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner()),
    )

    with pytest.raises(ValueError):
        project.create_plan("   ")


def test_create_plan_rejects_non_string_requirement():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner()),
    )

    with pytest.raises(TypeError):
        project.create_plan(None)


def test_create_plan_propagates_planner_failure():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FailingPlanner()),
    )

    with pytest.raises(RuntimeError, match="planner failed"):
        project.create_plan(
            "开发一个个人记账软件。"
        )


def test_create_plan_rejects_invalid_planner_result():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(
            InvalidPlannerResult()
        ),
    )

    with pytest.raises(
        ValueError,
        match="does not contain a valid plan",
    ):
        project.create_plan(
            "开发一个个人记账软件。"
        )


def test_build_task_manager():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner()),
    )

    manager = project.build_task_manager(
        _plan()
    )

    assert isinstance(manager, TaskManager)

    tasks = manager.get_all_tasks()

    assert len(tasks) == 3

    assert tasks[0].id == "TASK-001"
    assert tasks[0].role == "architect"
    assert tasks[0].status == "pending"

    assert tasks[1].id == "TASK-002"
    assert tasks[1].dependencies == ["TASK-001"]

    assert tasks[2].id == "TASK-003"
    assert tasks[2].dependencies == ["TASK-002"]


def test_build_task_manager_stores_last_task_manager():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner()),
    )

    manager = project.build_task_manager(
        _plan()
    )

    assert project.last_task_manager is manager


def test_build_task_manager_rejects_non_dict():
    project = ProjectOrchestrator(
        agent_router=FakeRouter(FakePlanner()),
    )

    with pytest.raises(TypeError):
        project.build_task_manager(None)


def test_create_orchestrator():
    planner = FakePlanner()
    router = FakeRouter(planner)

    captured = {}

    def factory(task_manager, agent_router):
        captured["task_manager"] = task_manager
        captured["agent_router"] = agent_router

        return FakeOrchestrator(
            task_manager,
            agent_router,
        )

    project = ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=factory,
    )

    manager = project.build_task_manager(
        _plan()
    )

    orchestrator = project.create_orchestrator(
        manager
    )

    assert isinstance(
        orchestrator,
        FakeOrchestrator,
    )

    assert captured["task_manager"] is manager
    assert captured["agent_router"] is router


def test_run_executes_orchestrator():
    planner = FakePlanner()
    router = FakeRouter(planner)

    captured = {}

    def factory(task_manager, agent_router):
        orchestrator = FakeOrchestrator(
            task_manager,
            agent_router,
        )

        captured["orchestrator"] = orchestrator

        return orchestrator

    project = ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=factory,
    )

    manager = project.run(
        "开发一个个人记账软件。"
    )

    orchestrator = captured["orchestrator"]

    assert orchestrator.run_called is True
    assert orchestrator.task_manager is manager
    assert orchestrator.agent_router is router

    assert project.last_plan == _plan()
    assert project.last_task_manager is manager


def test_run_returns_task_manager():
    planner = FakePlanner()
    router = FakeRouter(planner)

    def factory(task_manager, agent_router):
        return FakeOrchestrator(
            task_manager,
            agent_router,
        )

    project = ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=factory,
    )

    result = project.run(
        "开发一个个人记账软件。"
    )

    assert isinstance(
        result,
        TaskManager,
    )

    assert len(
        result.get_all_tasks()
    ) == 3


def test_run_does_not_execute_when_planner_fails():
    planner = FailingPlanner()
    router = FakeRouter(planner)

    orchestrator_created = False

    def factory(task_manager, agent_router):
        nonlocal orchestrator_created

        orchestrator_created = True

        return FakeOrchestrator(
            task_manager,
            agent_router,
        )

    project = ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=factory,
    )

    with pytest.raises(
        RuntimeError,
        match="planner failed",
    ):
        project.run(
            "开发一个个人记账软件。"
        )

    assert orchestrator_created is False