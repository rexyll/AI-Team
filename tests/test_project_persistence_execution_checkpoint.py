from __future__ import annotations

from threading import Event, Thread

from core.orchestrator import Orchestrator
from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.agent_router import AgentRouter
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


class MockAgent:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.calls = 0

    def run(self, task: Task) -> dict:
        self.calls += 1
        return {
            "status": self.status,
            "agent": task.role,
            "task_id": task.id,
            "message": self.status,
        }


class BlockingAgent(MockAgent):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def run(self, task: Task) -> dict:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("blocking agent was not released")
        return {
            "status": "completed",
            "agent": task.role,
            "task_id": task.id,
            "message": "completed after checkpoint",
        }


def _manager(*, status: str = "ready") -> TaskManager:
    return TaskManager([
        Task(
            id="TASK-001",
            title="checkpoint task",
            description="checkpoint task",
            role="architect",
            status=status,
        ),
    ])


def _plan() -> dict:
    return {
        "project": "Checkpoint Project",
        "summary": "Persist task execution boundaries",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "checkpoint task",
                "description": "checkpoint task",
                "role": "architect",
                "dependencies": [],
            },
        ],
    }


def test_orchestrator_state_change_hook_captures_ready_running_completed():
    manager = _manager()
    agent = MockAgent()
    router = AgentRouter()
    router.register("architect", agent)

    checkpoints: list[str] = []

    orchestrator = Orchestrator(manager, router)
    orchestrator.set_state_change_hook(
        lambda task_manager: checkpoints.append(
            task_manager.get_task("TASK-001").status
        )
    )

    orchestrator.run()

    assert checkpoints == ["ready", "running", "completed"]
    assert agent.calls == 1


def test_orchestrator_state_change_hook_captures_failed_terminal_state():
    manager = _manager()
    agent = MockAgent(status="failed")
    router = AgentRouter()
    router.register("architect", agent)

    checkpoints: list[str] = []

    orchestrator = Orchestrator(manager, router)
    orchestrator.set_state_change_hook(
        lambda task_manager: checkpoints.append(
            task_manager.get_task("TASK-001").status
        )
    )

    orchestrator.run()

    assert checkpoints == ["ready", "running", "failed"]
    assert manager.get_task("TASK-001").status == "failed"
    assert agent.calls == 1


def test_persisted_continue_writes_running_checkpoint_before_agent_finishes(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    manager = _manager()
    adapter.save(
        "PROJECT-001",
        plan=_plan(),
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project="Checkpoint Project"),
    )

    agent = BlockingAgent()
    router = AgentRouter()
    router.register("architect", agent)
    project = ProjectOrchestrator(agent_router=router)

    errors: list[BaseException] = []

    def run_continue() -> None:
        try:
            project.continue_persisted("PROJECT-001", adapter)
        except BaseException as exc:  # pragma: no cover - failure transport
            errors.append(exc)

    worker = Thread(target=run_continue)
    worker.start()

    assert agent.started.wait(timeout=5)

    running_snapshot = adapter.load("PROJECT-001")
    assert running_snapshot.task_manager.get_task("TASK-001").status == "running"

    agent.release.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []

    final_snapshot = adapter.load("PROJECT-001")
    assert final_snapshot.task_manager.get_task("TASK-001").status == "completed"
    assert final_snapshot.result is not None
    assert final_snapshot.result.success is True
