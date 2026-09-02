from collections.abc import Callable

from runtime.agent_router import AgentRouter
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow
from runtime.workflow_event_log import WorkflowEventLog


def create_task_workflow(
    task_manager: TaskManager,
    agent_router: AgentRouter,
    max_review_rounds: int = 3,
    state_change_hook: Callable[[TaskManager], None] | None = None,
    workflow_event_log: WorkflowEventLog | None = None,
    project_id: str | None = None,
    developer=None,
    execution_id: str | None = None,
) -> TaskWorkflow:
    """Build the canonical Developer -> Tester -> Reviewer workflow.

    ``developer`` can be supplied by the project orchestrator to select a
    specific member of the configured Developer pool. ``execution_id``
    correlates every workflow event with the host-owned execution identity.
    """
    selected_developer = (
        developer
        if developer is not None
        else agent_router.get_agent("developer")
    )
    tester = agent_router.get_agent("tester")
    reviewer = agent_router.get_agent("reviewer")

    return TaskWorkflow(
        task_manager=task_manager,
        developer=selected_developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=agent_router,
        max_review_rounds=max_review_rounds,
        state_change_hook=state_change_hook,
        workflow_event_log=workflow_event_log,
        project_id=project_id,
        execution_id=execution_id,
    )
