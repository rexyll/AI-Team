from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow
from runtime.workflow_event_log import WorkflowEventLog
from runtime.reviewer_reliability import ResilientReviewerAgent


class _Developer:
    role = "developer"

    def run(self, task):
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


class _Tester:
    role = "tester"

    def run(self, task):
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "passed",
        }


class _PrimaryReviewer:
    role = "reviewer"

    def __init__(self, error):
        self.error = error

    def run(self, task):
        raise self.error

    def build_context(self, task, *, all_tasks=None):
        return {"task_id": task.id, "all_tasks": all_tasks}


class _FallbackReviewer:
    role = "reviewer"

    def build_context(self, task, *, all_tasks=None):
        return {"task_id": task.id, "all_tasks": all_tasks}


def _workflow(*, reviewer, log=None, max_review_rounds=1, max_reviewer_recovery_attempts=1):
    task = Task(
        id="TASK-REVIEWER-RECOVERY-001",
        title="reviewer recovery",
        description="exercise reviewer reliability workflow boundary",
        role="developer",
        status="ready",
    )
    manager = TaskManager([task])
    router = AgentRouter()
    developer = _Developer()
    tester = _Tester()
    router.register("developer", developer)
    router.register("tester", tester)
    router.register("reviewer", reviewer)
    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
        max_review_rounds=max_review_rounds,
        max_reviewer_recovery_attempts=max_reviewer_recovery_attempts,
        workflow_event_log=log,
        project_id="PROJECT-REVIEWER-RECOVERY-001" if log is not None else None,
    )
    return task, manager, workflow


def test_reviewer_fallback_approval_completes_through_workflow_boundary():
    wrapper = ResilientReviewerAgent(
        _PrimaryReviewer(RuntimeError("primary reviewer unavailable")),
        _FallbackReviewer(),
    )
    wrapper._run_lightweight_fallback = lambda task: AgentResult(
        status="approved",
        agent="reviewer",
        task_id=task.id,
        message="APPROVED",
    )
    task, manager, workflow = _workflow(reviewer=wrapper)

    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert result.review_result["data"]["reviewer_execution"]["source"] == "fallback"
    assert result.error is None


def test_reviewer_fallback_exhaustion_fails_without_false_approval():
    wrapper = ResilientReviewerAgent(
        _PrimaryReviewer(RuntimeError("primary reviewer unavailable")),
        _FallbackReviewer(),
    )
    wrapper._run_lightweight_fallback = lambda task: (_ for _ in ()).throw(
        RuntimeError("fallback reviewer unavailable")
    )
    log = WorkflowEventLog()
    task, manager, workflow = _workflow(
        reviewer=wrapper,
        log=log,
        max_review_rounds=1,
        max_reviewer_recovery_attempts=1,
    )

    result = workflow.execute(task.id)

    assert result.status == "failed"
    assert result.review_result["status"] == "revision"
    assert result.review_result["data"]["reviewer_execution"]["source"] == "recovery"
    assert not any(event.event_type == "reviewer_approved" for event in log.list_for_task(task.id))
    assert [event.event_type for event in log.list_for_task(task.id)] == [
        "task_started",
        "developer_completed",
        "tester_passed",
        "review_started",
        "reviewer_fallback",
        "reviewer_retry",
        "review_started",
        "reviewer_fallback",
        "task_failed",
    ]
