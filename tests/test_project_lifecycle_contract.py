from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task_manager import TaskManager


PLAN = {
    "project": "lifecycle-demo",
    "summary": "exercise the complete project lifecycle",
    "tasks": [
        {
            "id": "TASK-LIFE-001",
            "title": "Architecture",
            "description": "define the architecture",
            "role": "architect",
            "dependencies": [],
        },
        {
            "id": "TASK-LIFE-002",
            "title": "Implementation",
            "description": "implement the feature",
            "role": "developer",
            "dependencies": ["TASK-LIFE-001"],
        },
    ],
}


class Planner:
    role = "planner"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "planner_completed",
            "agent": "planner",
            "task_id": task.id,
            "plan": PLAN,
        }


class Architect:
    role = "architect"

    def run(self, task):
        return {
            "status": "completed",
            "agent": "architect",
            "task_id": task.id,
            "message": "architecture complete",
        }


class Developer:
    role = "developer"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implementation complete",
        }


class LifecycleTester:
    role = "tester"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "tests passed",
        }


class Reviewer:
    role = "reviewer"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "approved",
        }


class Router:
    def __init__(self) -> None:
        self.planner = Planner()
        self.architect = Architect()
        self.developer = Developer()
        self.tester = LifecycleTester()
        self.reviewer = Reviewer()

    def get_agent(self, role):
        return {
            "planner": self.planner,
            "architect": self.architect,
            "developer": self.developer,
            "tester": self.tester,
            "reviewer": self.reviewer,
        }[role]


def test_project_lifecycle_runs_plan_build_execute_and_produces_workflow_artifacts():
    router = Router()
    project = ProjectOrchestrator(agent_router=router)

    result = project.run("build the lifecycle demo")

    assert result.project == "lifecycle-demo"
    assert result.success is True
    assert result.status == "completed"
    assert result.total_tasks == 2
    assert result.completed_tasks == 2
    assert router.planner.calls == 1
    assert router.developer.calls == 1
    assert router.tester.calls == 1
    assert router.reviewer.calls == 1

    manager = project.last_task_manager
    assert isinstance(manager, TaskManager)
    architect = manager.get_task("TASK-LIFE-001")
    developer = manager.get_task("TASK-LIFE-002")
    assert architect.status == "completed"
    assert developer.status == "completed"
    assert developer.result["status"] == "completed"
    assert developer.test_result["status"] == "passed"
    assert developer.review_result["status"] == "approved"


def test_project_lifecycle_persists_and_resumes_without_replanning(tmp_path):
    router = Router()
    project = ProjectOrchestrator(agent_router=router)
    result = project.run("build the lifecycle demo")

    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save(
        "LIFE-001",
        plan=project.last_plan,
        task_manager=project.last_task_manager,
        result=result,
    )

    restored_router = Router()
    resumed = ProjectOrchestrator(agent_router=restored_router)
    restored_result = resumed.resume_persisted("LIFE-001", adapter)

    assert restored_result == result
    assert restored_result.success is True
    assert restored_router.planner.calls == 0
    assert restored_router.developer.calls == 0
    assert restored_router.tester.calls == 0
    assert restored_router.reviewer.calls == 0


def test_project_lifecycle_continue_uses_persisted_runtime_without_replanning(tmp_path):
    router = Router()
    project = ProjectOrchestrator(agent_router=router)
    manager = project.build_task_manager(PLAN)

    manager.mark_ready("TASK-LIFE-001")
    manager.mark_running("TASK-LIFE-001")
    manager.mark_completed(
        "TASK-LIFE-001",
        {"status": "completed", "message": "restored"},
    )
    manager.mark_ready("TASK-LIFE-002")

    adapter = ProjectPersistenceAdapter(tmp_path)
    adapter.save("LIFE-002", plan=PLAN, task_manager=manager, result=None)

    continuation_router = Router()
    continuation = ProjectOrchestrator(agent_router=continuation_router)
    result = continuation.continue_persisted("LIFE-002", adapter)

    assert result.success is True
    assert result.status == "completed"
    assert continuation_router.planner.calls == 0
    assert continuation_router.developer.calls == 1
    assert continuation_router.tester.calls == 1
    assert continuation_router.reviewer.calls == 1

    restored = adapter.load("LIFE-002")
    assert restored.result == result
    assert restored.task_manager.get_task("TASK-LIFE-001").status == "completed"
    assert restored.task_manager.get_task("TASK-LIFE-002").status == "completed"
