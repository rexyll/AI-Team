from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class Agent:
    def __init__(self, role, status="completed"):
        self.role = role
        self.status = status
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": self.status,
            "agent": self.role,
            "task_id": task.id,
            "message": f"{self.role} result",
        }


def make_task(task_id="TASK-ROUTER"):
    return Task(
        id=task_id,
        title="router contract",
        description="verify workflow agent ownership",
        role="developer",
        status="ready",
    )


def make_router(developer, reviewer, tester=None):
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    if tester is not None:
        router.register("tester", tester)
    return router


def test_workflow_requires_explicit_agents_to_match_router_registry():
    developer = Agent("developer")
    reviewer = Agent("reviewer")
    other_developer = Agent("developer")
    router = make_router(developer, reviewer)

    try:
        TaskWorkflow(
            TaskManager([make_task()]),
            developer=other_developer,
            reviewer=reviewer,
            agent_router=router,
        )
    except ValueError as exc:
        assert "must be the instance registered" in str(exc)
    else:
        raise AssertionError("expected router/agent mismatch to be rejected")


def test_workflow_reads_stage_agents_from_router():
    developer = Agent("developer")
    reviewer = Agent("reviewer", status="approved")
    router = make_router(developer, reviewer)

    workflow = TaskWorkflow(
        TaskManager([make_task()]),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
    )

    replacement = Agent("developer")
    router.agents["developer"] = replacement

    assert workflow.developer is replacement
    assert workflow.developer is router.route("developer")


def test_optional_tester_is_router_owned():
    developer = Agent("developer")
    tester = Agent("tester", status="passed")
    reviewer = Agent("reviewer", status="approved")
    router = make_router(developer, reviewer, tester)

    workflow = TaskWorkflow(
        TaskManager([make_task()]),
        developer=developer,
        reviewer=reviewer,
        tester=tester,
        agent_router=router,
    )

    replacement = Agent("tester", status="passed")
    router.agents["tester"] = replacement

    assert workflow.tester is replacement
    assert workflow.tester is router.route("tester")
