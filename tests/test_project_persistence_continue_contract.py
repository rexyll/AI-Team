from __future__ import annotations

import pytest

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _manager() -> TaskManager:
    return TaskManager([
        Task(
            id="TASK-001",
            title="done",
            description="done",
            role="developer",
            status="completed",
        ),
        Task(
            id="TASK-002",
            title="ready",
            description="ready",
            role="developer",
            status="ready",
            dependencies=["TASK-001"],
        ),
    ])


def _failed_manager() -> TaskManager:
    return TaskManager([
        Task(
            id="TASK-001",
            title="done",
            description="done",
            role="developer",
            status="completed",
        ),
        Task(
            id="TASK-002",
            title="failed",
            description="failed",
            role="developer",
            status="failed",
            error="previous execution failed",
        ),
    ])


def _plan() -> dict:
    return {
        "project": "Continue Project",
        "summary": "Continue an interrupted project from persisted runtime state",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "done",
                "description": "done",
                "role": "developer",
                "dependencies": [],
            },
            {
                "id": "TASK-002",
                "title": "ready",
                "description": "ready",
                "role": "developer",
                "dependencies": ["TASK-001"],
            },
        ],
    }


class RecordingOrchestrator:
    """Small execution seam used to test project continuation in isolation."""

    executed_task_ids: list[str] = []

    def __init__(self, task_manager: TaskManager, agent_router: object):
        self.task_manager = task_manager
        self.agent_router = agent_router

    def run(self) -> None:
        for task in self.task_manager.get_all_tasks():
            if task.status != "ready":
                continue
            self.__class__.executed_task_ids.append(task.id)
            self.task_manager.mark_running(task.id)
            self.task_manager.mark_completed(
                task.id,
                {"status": "completed", "message": "continued"},
            )


def _factory(task_manager: TaskManager, agent_router: object) -> RecordingOrchestrator:
    return RecordingOrchestrator(task_manager, agent_router)


def _save(adapter: ProjectPersistenceAdapter, manager: TaskManager) -> None:
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Continue Project"),
    )


def test_persisted_project_can_be_continued_without_planner(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    _save(adapter, manager)
    RecordingOrchestrator.executed_task_ids = []

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=_factory,
    )
    result = project.continue_persisted("PROJECT-001", adapter)

    assert isinstance(result, ProjectResult)
    assert result.success is True
    assert result.status == "completed"
    assert result.completed_tasks == 2
    assert RecordingOrchestrator.executed_task_ids == ["TASK-002"]

    restored = adapter.load("PROJECT-001")
    assert restored.result == result
    assert restored.task_manager.get_task("TASK-001").status == "completed"
    assert restored.task_manager.get_task("TASK-002").status == "completed"


def test_persisted_continue_does_not_call_planner(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    _save(adapter, manager)
    RecordingOrchestrator.executed_task_ids = []

    class Router:
        def get_agent(self, role):
            raise AssertionError("planner must not be invoked during persisted continue")

    project = ProjectOrchestrator(
        agent_router=Router(),
        orchestrator_factory=_factory,
    )

    result = project.continue_persisted("PROJECT-001", adapter)

    assert result.success is True
    assert RecordingOrchestrator.executed_task_ids == ["TASK-002"]


def test_persisted_continue_never_reexecutes_completed_tasks(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    _save(adapter, manager)
    RecordingOrchestrator.executed_task_ids = []

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=_factory,
    )
    project.continue_persisted("PROJECT-001", adapter)

    assert RecordingOrchestrator.executed_task_ids == ["TASK-002"]


def test_persisted_continue_stops_cleanly_when_no_task_is_ready(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _failed_manager()
    _save(adapter, manager)

    project = ProjectOrchestrator(agent_router=object())
    result = project.continue_persisted("PROJECT-001", adapter)

    assert result.success is False
    assert result.status == "failed"
    assert result.completed_tasks == 1
    assert result.failed_tasks == ("TASK-002",)

    restored = adapter.load("PROJECT-001")
    assert restored.result == result


def test_persisted_continue_requires_existing_project(tmp_path):
    project = ProjectOrchestrator(agent_router=object())
    adapter = ProjectPersistenceAdapter(tmp_path)

    with pytest.raises(KeyError):
        project.continue_persisted("MISSING", adapter)


def test_persisted_continue_does_not_accept_runtime_task_manager_payload(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    project = ProjectOrchestrator(agent_router=object())

    with pytest.raises(TypeError):
        project.continue_persisted("PROJECT-001", object())
