import threading

import pytest

from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.mock import MockLLM
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.workflow import TaskWorkflow
from runtime.workflow_execution_lease import LeaseUnavailable, WorkflowExecutionLease
from runtime.workflow_root_tracing import attach_execution_lease


class _BlockingDeveloper(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def __init__(self, started, release, llm):
        super().__init__(llm=llm)
        self.started = started
        self.release = release
        self.calls = 0

    def run(self, task):
        self.calls += 1
        self.started.set()
        assert self.release.wait(timeout=5)
        return AgentResult(status="completed", agent=self.role, task_id=task.id, message="done")


class _Reviewer(BaseAgent):
    @property
    def role(self) -> str:
        return "reviewer"

    def run(self, task):
        return AgentResult(status="approved", agent=self.role, task_id=task.id, message="APPROVED")


def _workflow(manager, developer, reviewer, lease):
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    workflow = TaskWorkflow(task_manager=manager, developer=developer, reviewer=reviewer, agent_router=router)
    return attach_execution_lease(workflow, lease)


def test_canonical_workflow_rejects_duplicate_worker_while_task_is_in_flight():
    started = threading.Event()
    release = threading.Event()
    task = Task("TASK-DUP-E2E", "duplicate", "guard", "developer", status="ready")
    manager = TaskManager([task])
    lease_manager = FencedTaskLeaseManager(default_ttl_seconds=30)
    developer_a = _BlockingDeveloper(started, release, MockLLM("done"))
    developer_b = _BlockingDeveloper(threading.Event(), threading.Event(), MockLLM("done"))
    reviewer_a = _Reviewer(llm=MockLLM("APPROVED"))
    reviewer_b = _Reviewer(llm=MockLLM("APPROVED"))

    workflow_a = _workflow(manager, developer_a, reviewer_a, WorkflowExecutionLease(lease_manager, owner_id="worker-a"))
    workflow_b = _workflow(manager, developer_b, reviewer_b, WorkflowExecutionLease(lease_manager, owner_id="worker-b"))

    first_result = []
    first_error = []

    def run_first():
        try:
            first_result.append(workflow_a.execute(task.id))
        except Exception as exc:
            first_error.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    assert started.wait(timeout=5)

    with pytest.raises(LeaseUnavailable):
        workflow_b.execute(task.id)

    assert developer_b.calls == 0
    release.set()
    thread.join(timeout=5)

    assert not first_error
    assert first_result[0].status == "completed"
    assert developer_a.calls == 1
