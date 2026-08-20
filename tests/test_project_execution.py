from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_router import AgentRouter
from runtime.plan_builder import PlanBuilder


class FakePlanner:
    role = "planner"

    def run(self, task):
        return {
            "plan": {
                "project": "Personal Expense Manager",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "数据库设计",
                        "description": "设计 SQLite 数据库",
                        "role": "architect",
                    },
                    {
                        "id": "TASK-002",
                        "title": "数据库模块开发",
                        "description": "实现数据库模块",
                        "role": "developer",
                        "dependencies": [
                            "TASK-001"
                        ],
                    },
                ],
            }
        }


class FakeAgent:
    def __init__(self, role):
        self.role = role
        self.calls = []

    def run(self, task):
        self.calls.append(task)

        return {
            "status": "completed",
            "role": self.role,
            "task_id": task.id,
        }


class FakeOrchestrator:
    def __init__(
        self,
        task_manager,
        agent_router,
    ):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.run_called = False

    def run(self):
        self.run_called = True

        for task in self.task_manager.get_all_tasks():
            if task.status == "ready":
                task.status = "completed"


def create_test_router():
    router = AgentRouter()

    router.register(
        "planner",
        FakePlanner(),
    )

    router.register(
        "architect",
        FakeAgent("architect"),
    )

    router.register(
        "developer",
        FakeAgent("developer"),
    )

    router.register(
        "tester",
        FakeAgent("tester"),
    )

    router.register(
        "reviewer",
        FakeAgent("reviewer"),
    )

    return router


def test_project_execution_creates_plan():
    router = create_test_router()

    project = ProjectOrchestrator(
        agent_router=router,
    )

    plan = project.create_plan(
        "开发一个个人记账软件"
    )

    assert isinstance(plan, dict)

    assert (
        plan["project"]
        == "Personal Expense Manager"
    )

    assert len(plan["tasks"]) == 2


def test_project_execution_builds_task_manager():
    router = create_test_router()

    project = ProjectOrchestrator(
        agent_router=router,
    )

    plan = project.create_plan(
        "开发一个个人记账软件"
    )

    task_manager = project.build_task_manager(
        plan
    )

    tasks = task_manager.get_all_tasks()

    assert len(tasks) == 2

    assert tasks[0].id == "TASK-001"
    assert tasks[0].role == "architect"

    assert tasks[1].id == "TASK-002"
    assert tasks[1].role == "developer"

    assert tasks[1].dependencies == [
        "TASK-001"
    ]


def test_project_execution_creates_orchestrator():
    router = create_test_router()

    captured = {}

    def factory(
        task_manager,
        agent_router,
    ):
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

    task_manager = project.build_task_manager(
        project.create_plan(
            "开发一个个人记账软件"
        )
    )

    orchestrator = project.create_orchestrator(
        task_manager
    )

    assert (
        captured["orchestrator"]
        is orchestrator
    )

    assert (
        orchestrator.task_manager
        is task_manager
    )

    assert (
        orchestrator.agent_router
        is router
    )


def test_project_execution_runs_complete_pipeline():
    router = create_test_router()

    captured = {}

    def factory(
        task_manager,
        agent_router,
    ):
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

    task_manager = project.run(
        "开发一个个人记账软件"
    )

    assert project.last_plan is not None

    assert (
        project.last_task_manager
        is task_manager
    )

    orchestrator = captured["orchestrator"]

    assert orchestrator.run_called is True

    tasks = task_manager.get_all_tasks()

    assert len(tasks) == 2

    assert all(
        task.status == "completed"
        for task in tasks
    )


def test_project_execution_preserves_requirement():
    router = create_test_router()

    project = ProjectOrchestrator(
        agent_router=router,
    )

    plan = project.create_plan(
        "开发一个支持 SQLite 的个人记账软件"
    )

    assert plan is not None


def test_project_execution_uses_planner_role():
    router = create_test_router()

    planner = router.get_agent(
        "planner"
    )

    assert planner.role == "planner"


def test_project_execution_uses_default_plan_builder():
    router = create_test_router()

    project = ProjectOrchestrator(
        agent_router=router,
    )

    assert isinstance(
        project.plan_builder,
        PlanBuilder,
    )