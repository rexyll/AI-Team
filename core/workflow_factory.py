from runtime.agent_router import AgentRouter
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


def create_task_workflow(
    task_manager: TaskManager,
    agent_router: AgentRouter,
    max_review_rounds: int = 3,
) -> TaskWorkflow:
    """Build the canonical Developer -> Tester -> Reviewer workflow."""

    developer = agent_router.get_agent("developer")
    tester = agent_router.get_agent("tester")
    reviewer = agent_router.get_agent("reviewer")

    return TaskWorkflow(
        task_manager=task_manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=agent_router,
        max_review_rounds=max_review_rounds,
    )