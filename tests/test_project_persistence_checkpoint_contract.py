from __future__ import annotations

from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


class RecordingAdapter(ProjectPersistenceAdapter):
    def __init__(self, root):
        super().__init__(root)
        self.updates: list[tuple[str, dict[str, str], ProjectResult | None]] = []

    def update(self, project_id, *, plan, task_manager, result=None):
        self.updates.append(
            (
                project_id,
                {task.id: task.status for task in task_manager.get_all_tasks()},
                result,
            )
        )
        super().update(
            project_id,
            plan=plan,
            task_manager=task_manager,
            result=result,
        )


class HookedOrchestrator:
    def __init__(self, task_manager: TaskManager, agent_router: object):
        self.task_manager = task_manager
        self.agent_router = agent_router
        self.hook = None

    def set_state_change_hook(self, hook):
        self.hook = hook

    def run(self):
        task = self.task_manager.get_all_tasks()[0]
        if self.hook:
            self.hook(self.task_manager)
        self.task_manager.mark_running(task.id)
        if self.hook:
            self.hook(self.task_manager)
        self.task_manager.mark_completed(task.id, {"status": "completed"})
        if self.hook:
            self.hook(self.task_manager)


def _plan() -> dict:
    return {
        "project": "Checkpoint Project",
        "summary": "Verify durable continuation checkpoints",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "continue",
                "description": "continue",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def _manager() -> TaskManager:
    return TaskManager([
        Task(
            id="TASK-001",
            title="continue",
            description="continue",
            role="developer",
            status="ready",
        )
    ])


def _factory(task_manager, agent_router):
    return HookedOrchestrator(task_manager, agent_router)


def test_continue_persisted_checkpoints_each_execution_boundary(tmp_path):
    adapter = RecordingAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Checkpoint Project"),
    )

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=_factory,
    )
    result = project.continue_persisted("PROJECT-001", adapter)

    assert result.success is True
    assert [states for _, states, _ in adapter.updates] == [
        {"TASK-001": "ready"},
        {"TASK-001": "running"},
        {"TASK-001": "completed"},
    ]

    restored = adapter.load("PROJECT-001")
    assert restored.task_manager.get_task("TASK-001").status == "completed"
    assert restored.result == result


def test_continue_persisted_final_snapshot_is_authoritative(tmp_path):
    adapter = RecordingAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Checkpoint Project"),
    )

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=_factory,
    )
    result = project.continue_persisted("PROJECT-001", adapter)
    restored = adapter.load("PROJECT-001")

    assert restored.result == result
    assert restored.result is not None
    assert restored.result.status == "completed"
    assert restored.result.completed_tasks == 1


def test_continue_persisted_restores_plan_before_execution(tmp_path):
    adapter = RecordingAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Checkpoint Project"),
    )

    seen_projects: list[str | None] = []

    class InspectingOrchestrator(HookedOrchestrator):
        def run(self):
            seen_projects.append(project.last_plan.get("project") if project.last_plan else None)
            super().run()

    project = ProjectOrchestrator(
        agent_router=object(),
        orchestrator_factory=lambda tm, router: InspectingOrchestrator(tm, router),
    )
    project.continue_persisted("PROJECT-001", adapter)

    assert seen_projects == ["Checkpoint Project"]
