from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult


def test_project_execution_runs_complete_pipeline():
    router = create_test_router()

    captured = {}

    def factory(task_manager, agent_router):
        orchestrator = FakeOrchestrator(task_manager, agent_router)
        captured["orchestrator"] = orchestrator
        return orchestrator

    project = ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=factory,
    )

    result = project.run("开发一个个人记账软件")

    assert isinstance(result, ProjectResult)
    assert project.last_plan is not None
    assert project.last_task_manager is not None
    assert project.last_result is result

    orchestrator = captured["orchestrator"]
    assert orchestrator.run_called is True
    assert orchestrator.task_manager is project.last_task_manager

    tasks = project.last_task_manager.get_all_tasks()
    assert len(tasks) == 2
    assert all(task.status == "completed" for task in tasks)

    assert result.success is True
    assert result.status == "completed"
    assert result.total_tasks == 2
    assert result.completed_tasks == 2
    assert result.failed_tasks == ()
    assert result.blocked_tasks == ()


def test_project_execution_preserves_requirement():
    router = create_test_router()

    project = ProjectOrchestrator(agent_router=router)

    plan = project.create_plan("开发一个支持 SQLite 的个人记账软件")

    assert plan is not None
