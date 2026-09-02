from __future__ import annotations

from agents.mock_agents import MockAgent
from core.orchestrator import Orchestrator
from mcp_bridge.orchestration import MCPOrchestrationBoundary
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog


def _router() -> AgentRouter:
    router = AgentRouter()
    router.register(MockAgent("developer"))
    router.register(MockAgent("tester"))
    router.register(MockAgent("reviewer"))
    return router


def test_orchestrator_retry_event_preserves_execution_identity() -> None:
    manager = TaskManager(
        [Task(id="TASK-RETRY", title="Retry", description="retry", role="developer", max_retries=2)]
    )
    manager.mark_ready("TASK-RETRY")
    manager.mark_running("TASK-RETRY")
    manager.mark_failed("TASK-RETRY", "transient failure")
    event_log = WorkflowEventLog()
    orchestrator = Orchestrator(
        manager,
        _router(),
        workflow_event_log=event_log,
        project_id="PROJECT-RETRY",
    )

    assert orchestrator._apply_retry_policy(
        manager.get_task("TASK-RETRY"),
        RuntimeError("transient failure"),
        execution_id="exec-retry-001",
    ) is True

    events = event_log.list_for_task("TASK-RETRY")
    retry_events = [event for event in events if event.event_type == "task_retrying"]
    assert len(retry_events) == 1
    assert retry_events[0].payload["execution_id"] == "exec-retry-001"
    assert manager.get_task("TASK-RETRY").status == "ready"


def test_mcp_idempotency_recovers_completed_execution_without_new_execution_id() -> None:
    manager = TaskManager([Task(id="TASK-IDEMP", title="Idempotent", description="done", role="developer")])
    manager.mark_ready("TASK-IDEMP")
    event_log = WorkflowEventLog()
    calls: list[str] = []

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            calls.append(execution_id)
            task = manager.get_task(task_id)
            manager.mark_running(task_id)
            manager.mark_completed(task_id, MockAgent("developer").run(task))
            return manager.get_task(task_id)

    boundary = MCPOrchestrationBoundary(
        manager,
        agent_router=_router(),
        workflow_factory=lambda _task_id: Workflow(),
        workflow_event_log=event_log,
        project_id="PROJECT-IDEMP",
    )

    first = boundary.execute_task("TASK-IDEMP", idempotency_key="idem-001")
    second = boundary.execute_task("TASK-IDEMP", idempotency_key="idem-001")

    assert first["execution_id"] == second["execution_id"]
    assert len(calls) == 1
    assert boundary.execution_status(first["execution_id"])["status"] == "completed"
    history = boundary.execution_history("TASK-IDEMP")
    assert {item["execution_id"] for item in history} == {first["execution_id"]}


def test_mcp_boundary_marks_returned_failed_task_as_failed_execution() -> None:
    manager = TaskManager([Task(id="TASK-FAILED", title="Failed", description="fail", role="developer")])
    manager.mark_ready("TASK-FAILED")
    event_log = WorkflowEventLog()

    class Workflow:
        def execute(self, task_id: str, *, execution_id: str):
            manager.mark_running(task_id)
            manager.mark_failed(task_id, "workflow failed")
            return manager.get_task(task_id)

    boundary = MCPOrchestrationBoundary(
        manager,
        workflow_factory=lambda _task_id: Workflow(),
        workflow_event_log=event_log,
        project_id="PROJECT-FAILED",
    )

    result = boundary.execute_task("TASK-FAILED")

    assert result["status"] == "failed"
    status = boundary.execution_status(result["execution_id"])
    assert status["status"] == "failed"
    assert status["error_type"] == "TaskExecutionFailed"
