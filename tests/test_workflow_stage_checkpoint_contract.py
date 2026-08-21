from __future__ import annotations

import pytest

from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class Developer:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def run(self, task):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


class Tester:
    def run(self, task):
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "tests passed",
        }


class Reviewer:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return self.results.pop(0)


def _workflow(developer, reviewer, checkpoint):
    task = Task(
        id="TASK-001",
        title="checkpoint test",
        description="verify stage checkpoint boundaries",
        role="developer",
        status="ready",
    )
    manager = TaskManager([task])
    router = AgentRouter()
    router.register("developer", developer)
    router.register("tester", Tester())
    router.register("reviewer", reviewer)
    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=router.get_agent("tester"),
        reviewer=reviewer,
        agent_router=router,
        state_change_hook=checkpoint,
    )
    return manager, workflow


def test_stage_checkpoints_capture_each_success_boundary():
    snapshots: list[str] = []
    developer = Developer()
    reviewer = Reviewer([
        {
            "status": "approved",
            "agent": "reviewer",
            "task_id": "TASK-001",
            "message": "approved",
        }
    ])

    manager, workflow = _workflow(
        developer,
        reviewer,
        lambda manager: snapshots.append(manager.get_task("TASK-001").status),
    )

    result = workflow.execute("TASK-001")

    assert result.status == "completed"
    assert snapshots == ["running", "review_pending", "reviewing", "completed"]


def test_revision_round_checkpoint_returns_to_running_before_next_round():
    snapshots: list[str] = []
    developer = Developer()
    reviewer = Reviewer([
        {
            "status": "revision",
            "agent": "reviewer",
            "task_id": "TASK-001",
            "message": "add tests",
        },
        {
            "status": "approved",
            "agent": "reviewer",
            "task_id": "TASK-001",
            "message": "approved",
        },
    ])

    manager, workflow = _workflow(
        developer,
        reviewer,
        lambda manager: snapshots.append(manager.get_task("TASK-001").status),
    )

    result = workflow.execute("TASK-001")

    assert result.status == "completed"
    assert snapshots == [
        "running",
        "review_pending",
        "reviewing",
        "running",
        "review_pending",
        "reviewing",
        "completed",
    ]


def test_stage_checkpoint_is_emitted_when_developer_fails():
    snapshots: list[str] = []
    developer = Developer(RuntimeError("developer crashed"))
    reviewer = Reviewer([])

    manager, workflow = _workflow(
        developer,
        reviewer,
        lambda manager: snapshots.append(manager.get_task("TASK-001").status),
    )

    with pytest.raises(RuntimeError, match="developer crashed"):
        workflow.execute("TASK-001")

    assert snapshots == ["running", "failed"]
    assert manager.get_task("TASK-001").status == "failed"


def test_stage_checkpoint_hook_is_optional_and_preserves_existing_workflow_contract():
    developer = Developer()
    reviewer = Reviewer([
        {
            "status": "approved",
            "agent": "reviewer",
            "task_id": "TASK-001",
            "message": "approved",
        }
    ])

    manager, workflow = _workflow(developer, reviewer, None)

    result = workflow.execute("TASK-001")

    assert result.status == "completed"
    assert developer.calls == 1
    assert reviewer.calls == 1
