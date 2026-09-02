from __future__ import annotations

from agents.mock_agents import MockAgent
from core.workflow_factory import create_task_workflow
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import StageOutcome, WorkflowStage
from runtime.workflow_event_log import WorkflowEventLog


def test_mcp_execution_identity_flows_through_canonical_developer_workflow() -> None:
    manager = TaskManager(
        [Task(id="TASK-DEV", title="Developer task", description="implement", role="developer")]
    )
    router = AgentRouter()
    router.register(MockAgent("developer"))
    router.register(MockAgent("tester"))
    router.register(MockAgent("reviewer"))
    event_log = WorkflowEventLog()

    workflow = create_task_workflow(
        task_manager=manager,
        agent_router=router,
        workflow_event_log=event_log,
        project_id="PROJECT-DEV",
        developer=router.get_agent("developer"),
        execution_id="exec-developer-001",
    )
    workflow._run_developer = lambda task: StageOutcome.success(
        WorkflowStage.DEVELOPER,
        AgentResult(status="completed", agent="developer", task_id=task.id, message="done"),
    )
    workflow._run_tester = lambda task: StageOutcome.success(
        WorkflowStage.TESTER,
        AgentResult(status="passed", agent="tester", task_id=task.id, message="passed"),
    )
    workflow._run_reviewer = lambda task: StageOutcome.success(
        WorkflowStage.REVIEWER,
        AgentResult(status="approved", agent="reviewer", task_id=task.id, message="approved"),
    )

    manager.mark_ready("TASK-DEV")
    result = workflow.execute("TASK-DEV", execution_id="exec-developer-001")

    assert result.status == "completed"
    assert result.context["execution_id"] == "exec-developer-001"
    events = event_log.list_for_project("PROJECT-DEV")
    assert events
    assert all(
        event.payload.get("execution_id") == "exec-developer-001"
        for event in events
    )
