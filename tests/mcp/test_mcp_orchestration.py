from __future__ import annotations

import pytest

from agents.mock_agents import MockAgent
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
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

    assert task == {
        "id": "TASK-001", "title": "First", "role": "developer", "status": "pending",
        "dependencies": [], "error": None, "review_round": 0,
        "retry_attempt": 0, "max_retries": 0, "cancellation_requested": False,
    }
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
    assert agents == [
        {"role": "developer", "registered": True},
        {"role": "tester", "registered": True},
    ]
    assert all(set(item) == {"role", "registered"} for item in agents)


def test_workflow_execution_is_explicitly_disabled_without_host_factory() -> None:
    boundary, _ = _boundary()
    assert boundary.workflow_capabilities() == {
        "task_read": True, "agent_read": True,
        "workflow_execute": False, "workflow_cancel": False,
    }
    with pytest.raises(RuntimeError, match="workflow execution is not configured"):
        boundary.execute_task("TASK-001")


def test_workflow_execution_requires_execute_contract() -> None:
    _, manager = _boundary()
    boundary = MCPOrchestrationBoundary(manager, workflow_factory=lambda _: object())
    with pytest.raises(TypeError, match="execute\(task_id\)"):
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
