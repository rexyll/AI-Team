from __future__ import annotations

import pytest

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _manager() -> TaskManager:
    return TaskManager([
        Task(id="TASK-001", title="done", description="done", status="completed"),
        Task(id="TASK-002", title="ready", description="ready", status="ready"),
    ])


def _plan() -> dict:
    return {
        "project": "Resume Project",
        "tasks": [
            {"id": "TASK-001", "title": "done", "description": "done", "role": "developer", "dependencies": []},
            {"id": "TASK-002", "title": "ready", "description": "ready", "role": "developer", "dependencies": ["TASK-001"]},
        ],
    }


def test_persisted_project_can_be_resumed_without_planner(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save("PROJECT-001", plan=_plan(), task_manager=manager, result=ProjectResult.from_task_manager(manager, project="Resume Project"))

    project = ProjectOrchestrator(agent_router=object())
    result = project.resume_persisted("PROJECT-001", adapter)

    assert isinstance(result, ProjectResult)
    assert project.last_plan == _plan()
    assert project.last_task_manager is not None
    assert project.last_task_manager.get_task("TASK-001").status == "completed"


def test_persisted_resume_does_not_call_planner(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save("PROJECT-001", plan=_plan(), task_manager=manager, result=ProjectResult.from_task_manager(manager, project="Resume Project"))

    class Router:
        def get_agent(self, role):
            raise AssertionError("planner must not be invoked during persisted resume")

    project = ProjectOrchestrator(agent_router=Router())
    project.resume_persisted("PROJECT-001", adapter)


def test_persisted_resume_requires_existing_project(tmp_path):
    project = ProjectOrchestrator(agent_router=object())
    adapter = ProjectPersistenceAdapter(tmp_path)
    with pytest.raises(KeyError):
        project.resume_persisted("MISSING", adapter)


def test_persisted_resume_does_not_accept_runtime_task_manager_payload(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    project = ProjectOrchestrator(agent_router=object())
    with pytest.raises(TypeError):
        project.resume_persisted("PROJECT-001", object())
