import pytest

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.task import Task
from runtime.task_manager import TaskManager


class FakeRouter:
    pass


class FakeOrchestrator:
    def __init__(self, task_manager, agent_router):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.run_calls = 0

    def run(self):
        self.run_calls += 1
        for task in self.task_manager.get_all_tasks():
            if task.status == "ready":
                self.task_manager.mark_running(task.id)
                self.task_manager.mark_completed(task.id, {"status": "completed"})


def _project(captured):
    def factory(task_manager, agent_router):
        orchestrator = FakeOrchestrator(task_manager, agent_router)
        captured["orchestrator"] = orchestrator
        return orchestrator

    return ProjectOrchestrator(
        agent_router=FakeRouter(),
        orchestrator_factory=factory,
    )


def test_resume_requires_existing_in_memory_execution_state():
    project = _project({})

    with pytest.raises(ValueError, match="no in-memory task manager"):
        project.resume()


def test_resume_uses_existing_task_manager_without_replanning():
    captured = {}
    project = _project(captured)
    completed = Task(
        id="RESUME-001",
        title="completed",
        description="already complete",
        role="architect",
        status="completed",
    )
    ready = Task(
        id="RESUME-002",
        title="ready",
        description="continue execution",
        role="architect",
        status="ready",
    )
    manager = TaskManager([completed, ready])
    project.last_task_manager = manager
    project.last_plan = {"project": "resume-test"}

    result = project.resume()

    assert captured["orchestrator"].run_calls == 1
    assert captured["orchestrator"].task_manager is manager
    assert manager.get_task("RESUME-001").status == "completed"
    assert manager.get_task("RESUME-002").status == "completed"
    assert project.last_task_manager is manager
    assert isinstance(result, ProjectResult)
    assert result.status == "completed"


def test_resume_can_use_explicit_task_manager_and_never_rebuilds_plan():
    captured = {}
    project = _project(captured)
    manager = TaskManager(
        [
            Task(
                id="RESUME-003",
                title="ready",
                description="continue",
                role="architect",
                status="ready",
            )
        ]
    )

    result = project.resume(manager)

    assert captured["orchestrator"].task_manager is manager
    assert project.last_plan is None
    assert project.last_task_manager is manager
    assert result.project is None
    assert manager.get_task("RESUME-003").status == "completed"


def test_resume_does_not_invoke_planner():
    class PlannerFailRouter:
        def get_agent(self, role):
            raise AssertionError("planner must not be invoked during resume")

    project = ProjectOrchestrator(agent_router=PlannerFailRouter())
    manager = TaskManager(
        [
            Task(
                id="RESUME-004",
                title="ready",
                description="continue",
                role="architect",
                status="ready",
            )
        ]
    )
    project.orchestrator_factory = lambda task_manager, agent_router: FakeOrchestrator(
        task_manager,
        agent_router,
    )

    result = project.resume(manager)

    assert result.status == "completed"
