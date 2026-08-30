from threading import Barrier, Lock, Thread

import pytest

from runtime.agent_router import AgentRouter
from runtime.agent_result import AgentResult
from runtime.lease_guarded_workflow import LeaseGuardedTaskWorkflow
from runtime.task import Task
from runtime.task_lease import LeaseUnavailable
from runtime.task_manager import TaskManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.workflow_execution_lease import WorkflowExecutionLease


class _Developer:
    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def run(self, task):
        self.entered.acquire()
        self.release.wait()
        return AgentResult("completed", "developer", task.id, "done")


class _Reviewer:
    def run(self, task):
        return AgentResult("approved", "reviewer", task.id, "approved")


def _workflow(task, developer, owner):
    router = AgentRouter()
    router.register("developer", developer)
    reviewer = _Reviewer()
    router.register("reviewer", reviewer)
    return LeaseGuardedTaskWorkflow(
        task_manager=TaskManager([task]),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        execution_lease=WorkflowExecutionLease(lease_manager, owner_id=owner),
    )


lease_manager = FencedTaskLeaseManager(default_ttl_seconds=30)


def test_only_one_workflow_worker_enters_execution():
    global lease_manager
    lease_manager = FencedTaskLeaseManager(default_ttl_seconds=30)
    task_a = Task("TASK-CONCURRENT", "concurrent", "test", "developer", status="ready")
    task_b = Task("TASK-CONCURRENT", "concurrent", "test", "developer", status="ready")
    entered = Lock()
    release = Barrier(2)
    first = _workflow(task_a, _Developer(entered, release), "worker-a")
    second = _workflow(task_b, _Developer(Lock(), Barrier(2)), "worker-b")

    errors = []
    results = []

    def run(workflow):
        try:
            results.append(workflow.execute("TASK-CONCURRENT"))
        except Exception as exc:
            errors.append(exc)

    t1 = Thread(target=run, args=(first,))
    t1.start()
    entered.acquire()
    t2 = Thread(target=run, args=(second,))
    t2.start()
    t2.join(timeout=2)
    assert any(isinstance(error, LeaseUnavailable) for error in errors)
    release.wait(timeout=2)
    t1.join(timeout=2)
    assert len(results) == 1


def test_lease_guard_releases_after_workflow_exception():
    manager = FencedTaskLeaseManager(default_ttl_seconds=30)
    execution = WorkflowExecutionLease(manager, owner_id="worker-a")
    with pytest.raises(RuntimeError):
        execution.run("TASK-FAIL", lambda lease: (_ for _ in ()).throw(RuntimeError("boom")))
    assert manager.get("TASK-FAIL") is None
