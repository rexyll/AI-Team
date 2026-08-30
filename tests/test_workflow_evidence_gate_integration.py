from runtime.agent_result import AgentResult
from runtime.provenance import agent_feedback_provenance
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import StageOutcome, TaskWorkflow, WorkflowStage


def _workflow(task: Task, *, tester=object()) -> TaskWorkflow:
    return TaskWorkflow(
        TaskManager([task]),
        developer=object(),
        reviewer=object(),
        tester=tester,
        agent_router=object(),
    )


def _developer_result(task_id: str) -> dict:
    return {
        "status": "completed",
        "agent": "developer",
        "task_id": task_id,
        "message": "done",
        "data": {},
    }


def _tester_result(task_id: str, *, parent_evidence_id: str | None = None, with_provenance: bool = True) -> AgentResult:
    data = {"decision": "passed"}
    if with_provenance:
        data["provenance"] = agent_feedback_provenance(
            task_id=task_id,
            agent_role="tester",
            evidence_id=f"tester:{task_id}",
            parent_evidence_id=parent_evidence_id,
        ).to_dict()
    return AgentResult(
        status="passed",
        agent="tester",
        task_id=task_id,
        message="TEST_PASSED",
        data=data,
    )


def _reviewer_result(task_id: str, *, parent_evidence_id: str | None = None, with_provenance: bool = True) -> AgentResult:
    data = {"decision": "approved"}
    if with_provenance:
        data["provenance"] = agent_feedback_provenance(
            task_id=task_id,
            agent_role="reviewer",
            evidence_id=f"reviewer:{task_id}:round:1",
            parent_evidence_id=parent_evidence_id,
        ).to_dict()
    return AgentResult(
        status="approved",
        agent="reviewer",
        task_id=task_id,
        message="APPROVED",
        data=data,
    )


def test_tester_pass_requires_explicit_provenance_before_reviewing() -> None:
    task = Task("TASK-001", "gate", "gate", "developer", status="review_pending")
    task.result = _developer_result(task.id)
    workflow = _workflow(task)
    outcome = StageOutcome.success(
        WorkflowStage.TESTER,
        _tester_result(task.id, with_provenance=False),
    )

    passed = workflow._handle_tester_result(task, outcome)

    assert passed is False
    assert task.status == "failed"
    assert "Tester evidence validation failed" in (task.error or "")


def test_tester_pass_must_link_current_developer_result() -> None:
    task = Task("TASK-001", "gate", "gate", "developer", status="review_pending")
    task.result = _developer_result(task.id)
    workflow = _workflow(task)
    outcome = StageOutcome.success(
        WorkflowStage.TESTER,
        _tester_result(task.id, parent_evidence_id="developer:OTHER"),
    )

    passed = workflow._handle_tester_result(task, outcome)

    assert passed is False
    assert task.status == "failed"
    assert "missing parent evidence" in (task.error or "") or "current parent evidence" in (task.error or "")


def test_tester_pass_with_current_developer_lineage_enters_reviewing() -> None:
    task = Task("TASK-001", "gate", "gate", "developer", status="review_pending")
    task.result = _developer_result(task.id)
    workflow = _workflow(task)
    outcome = StageOutcome.success(
        WorkflowStage.TESTER,
        _tester_result(task.id, parent_evidence_id=f"developer:{task.id}"),
    )

    passed = workflow._handle_tester_result(task, outcome)

    assert passed is True
    assert task.status == "reviewing"
    assert task.context["tester_feedback"]["data"]["provenance"]["evidence_id"] == f"tester:{task.id}"


def test_reviewer_approval_requires_explicit_provenance_before_completion() -> None:
    task = Task("TASK-001", "gate", "gate", "developer", status="reviewing")
    task.result = _developer_result(task.id)
    tester = _tester_result(task.id, parent_evidence_id=f"developer:{task.id}")
    task.context["tester_feedback"] = tester.to_dict()
    workflow = _workflow(task)
    outcome = StageOutcome.success(
        WorkflowStage.REVIEWER,
        _reviewer_result(task.id, with_provenance=False),
    )

    action = workflow._apply_reviewer_outcome(task, outcome)

    assert action == "failed"
    assert task.status == "failed"
    assert "Reviewer evidence validation failed" in (task.error or "")


def test_reviewer_approval_must_link_current_tester_evidence() -> None:
    task = Task("TASK-001", "gate", "gate", "developer", status="reviewing")
    task.result = _developer_result(task.id)
    tester = _tester_result(task.id, parent_evidence_id=f"developer:{task.id}")
    task.context["tester_feedback"] = tester.to_dict()
    workflow = _workflow(task)
    outcome = StageOutcome.success(
        WorkflowStage.REVIEWER,
        _reviewer_result(task.id, parent_evidence_id="tester:OTHER"),
    )

    action = workflow._apply_reviewer_outcome(task, outcome)

    assert action == "failed"
    assert task.status == "failed"
    assert "missing parent evidence" in (task.error or "") or "current parent evidence" in (task.error or "")


def test_complete_tester_reviewer_lineage_allows_completion() -> None:
    task = Task("TASK-001", "gate", "gate", "developer", status="reviewing")
    task.result = _developer_result(task.id)
    tester = _tester_result(task.id, parent_evidence_id=f"developer:{task.id}")
    task.context["tester_feedback"] = tester.to_dict()
    workflow = _workflow(task)
    outcome = StageOutcome.success(
        WorkflowStage.REVIEWER,
        _reviewer_result(task.id, parent_evidence_id=f"tester:{task.id}"),
    )

    action = workflow._apply_reviewer_outcome(task, outcome)

    assert action == "completed"
    assert task.status == "completed"
    assert task.review_result["data"]["provenance"]["parent_evidence_id"] == f"tester:{task.id}"
