from __future__ import annotations

import threading
import time

import pytest

from agents.mock_agents import MockAgent
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog
from mcp_bridge.orchestration import MCPOrchestrationBoundary


def _boundary() -> tuple[MCPOrchestrationBoundary, TaskManager]:
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
        Task(id="TASK-002", title="Second", description="second", role="tester", dependencies=["TASK-001"]),
    ])
    router = AgentRouter()
    router.register(MockAgent("developer"))
    router.register(MockAgent("tester"))
    return MCPOrchestrationBoundary(manager, agent_router=router), manager


def test_task_projection_excludes_mutable_runtime_payloads() -> None:
    boundary, manager = _boundary()
    manager.get_task("TASK-001").context["secret"] = "do-not-expose"
    manager.get_task("TASK-001").result["large"] = "runtime-result"
    task = boundary.get_task("TASK-001")
    assert task == {"id": "TASK-001", "title": "First", "role": "developer", "status": "pending", "dependencies": [], "error": None, "review_round": 0, "retry_attempt": 0, "max_retries": 0, "cancellation_requested": False}
    assert "context" not in task
    assert "result" not in task


def test_ready_tasks_uses_canonical_task_manager_semantics() -> None:
    boundary, manager = _boundary()
    ready = boundary.ready_tasks()
    assert [task["id"] for task in ready] == ["TASK-001"]
    assert manager.get_task("TASK-001").status == "ready"


def test_agent_projection_does_not_expose_agent_objects() -> None:
    boundary, _ = _boundary()
    agents = boundary.agents()
    assert agents == [{"role": "developer", "registered": True}, {"role": "tester", "registered": True}]
    assert all(set(item) == {"role", "registered"} for item in agents)


def test_workflow_execution_is_explicitly_disabled_without_host_factory() -> None:
    boundary, _ = _boundary()
    assert boundary.workflow_capabilities() == {"task_read": True, "agent_read": True, "workflow_execute": False, "workflow_cancel": False, "execution_observability": False, "execution_status": False, "execution_idempotency": False}
    with pytest.raises(RuntimeError, match="workflow execution is not configured"):
        boundary.execute_task("TASK-001")


def test_workflow_execution_requires_execute_contract() -> None:
    _, manager = _boundary()
    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: object())
    with pytest.raises(TypeError, match="execute\\(task_id\\)"):
        boundary.execute_task("TASK-001")


def test_workflow_execution_returns_only_task_projection() -> None:
    _, manager = _boundary()

    class FakeWorkflow:
        def execute(self, task_id: str):
            task = manager.get_task(task_id)
            task.status = "completed"
            task.context["internal"] = "hidden"
            return task

    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: FakeWorkflow())
    result = boundary.execute_task("TASK-001")
    assert result["id"] == "TASK-001"
    assert result["status"] == "completed"
    assert "context" not in result
    assert result["execution_id"]


def test_from_orchestrator_reuses_host_task_manager_and_router() -> None:
    manager = TaskManager([Task(id="TASK-001", title="First", description="first", role="developer")])
    router = AgentRouter()
    router.register(MockAgent("developer"))

    class Host:
        def __init__(self):
            self.task_manager = manager
            self.agent_router = router
            self.calls = 0

        def execute_task(self, task_id: str, *, execution_id: str):
            self.calls += 1
            task = self.task_manager.get_task(task_id)
            task.status = "completed"
            task.context["execution_id"] = execution_id
            return task

    host = Host()
    boundary = MCPOrchestrationBoundary.from_orchestrator(host)
    result = boundary.execute_task("TASK-001")
    assert result["status"] == "completed"
    assert result["execution_id"]
    assert host.calls == 1
    assert boundary._task_manager is manager
    assert boundary._agent_router is router


def test_execute_rejects_task_already_active() -> None:
    boundary, manager = _boundary()
    manager.get_task("TASK-001").status = "running"
    boundary_with_workflow = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: object())
    with pytest.raises(RuntimeError, match="already active"):
        boundary_with_workflow.execute_task("TASK-001")


def test_execute_rejects_duplicate_concurrent_mcp_start() -> None:
    manager = TaskManager([Task(id="TASK-001", title="First", description="first", role="developer")])
    entered = threading.Event()
    release = threading.Event()

    class SlowWorkflow:
        def execute(self, task_id: str, *, execution_id: str):
            entered.set()
            release.wait(timeout=2)
            task = manager.get_task(task_id)
            task.status = "completed"
            return task

    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: SlowWorkflow())
    first_result: list[dict] = []

    def run_first():
        first_result.append(boundary.execute_task("TASK-001"))

    thread = threading.Thread(target=run_first)
    thread.start()
    assert entered.wait(timeout=2)
    time.sleep(0.02)
    with pytest.raises(RuntimeError, match="already active|already being executed"):
        boundary.execute_task("TASK-001")
    release.set()
    thread.join(timeout=2)
    assert first_result[0]["status"] == "completed"


def test_execution_status_projects_active_and_completed_state() -> None:
    manager = TaskManager([Task(id="TASK-001", title="First", description="first", role="developer")])
    event_log = WorkflowEventLog()
    entered = threading.Event()
    release = threading.Event()

    class SlowWorkflow:
        def execute(self, task_id: str, *, execution_id: str):
            entered.set()
            release.wait(timeout=2)
            task = manager.get_task(task_id)
            task.status = "completed"
            return task

    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: SlowWorkflow(), workflow_event_log=event_log, project_id="PROJECT-001")
    result: list[dict] = []
    thread = threading.Thread(target=lambda: result.append(boundary.execute_task("TASK-001")))
    thread.start()
    assert entered.wait(timeout=2)
    execution_id = next(iter(event.payload["execution_id"] for event in event_log.list_for_project("PROJECT-001") if event.event_type == "mcp_task_execution_requested"))
    requested = next(event for event in event_log.list_for_project("PROJECT-001") if event.event_type == "mcp_task_execution_requested")
    assert boundary.execution_status(execution_id) == {"execution_id": execution_id, "task_id": "TASK-001", "status": "active", "started_at": requested.occurred_at}
    release.set()
    thread.join(timeout=2)
    assert boundary.execution_status(execution_id)["status"] == "completed"
    assert boundary.execution_status(execution_id)["task_status"] == "completed"
    assert result[0]["execution_id"] == execution_id


def test_idempotency_key_reuses_completed_execution_without_rerun() -> None:
    manager = TaskManager([Task(id="TASK-001", title="First", description="first", role="developer")])
    event_log = WorkflowEventLog()
    calls = 0

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            nonlocal calls
            calls += 1
            task = manager.get_task(task_id)
            task.status = "completed"
            return task

    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: Workflow(), workflow_event_log=event_log, project_id="PROJECT-001")
    first = boundary.execute_task("TASK-001", idempotency_key="request-001")
    second = boundary.execute_task("TASK-001", idempotency_key="request-001")
    assert calls == 1
    assert second == first


def test_idempotency_key_cannot_be_reused_for_another_task() -> None:
    manager = TaskManager([
        Task(id="TASK-001", title="First", description="first", role="developer"),
        Task(id="TASK-002", title="Second", description="second", role="developer"),
    ])
    event_log = WorkflowEventLog()

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            task = manager.get_task(task_id)
            task.status = "completed"
            return task

    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: Workflow(), workflow_event_log=event_log, project_id="PROJECT-001")
    boundary.execute_task("TASK-001", idempotency_key="request-001")
    with pytest.raises(ValueError, match="different task"):
        boundary.execute_task("TASK-002", idempotency_key="request-001")


def test_idempotency_requires_execution_observability() -> None:
    boundary, _ = _boundary()
    with pytest.raises(RuntimeError, match="execution observability"):
        boundary.execute_task("TASK-001", idempotency_key="request-001")


def test_execution_status_rejects_unknown_execution() -> None:
    boundary, _ = _boundary()
    with pytest.raises(KeyError, match="Unknown execution id"):
        boundary.execution_status("missing")
