from runtime.agent_result import AgentResult
from runtime.workflow import StageOutcome, WorkflowStage


def test_stage_outcome_status_comes_from_agent_result():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
        data={},
    )

    outcome = StageOutcome.success(
        WorkflowStage.DEVELOPER,
        result,
    )

    assert outcome.status == "completed"
    
    
def test_stage_outcome_failure():
    exc = RuntimeError("boom")

    outcome = StageOutcome.failure(
        WorkflowStage.DEVELOPER,
        exc,
    )

    assert outcome.failed
    assert outcome.exception is exc
    assert outcome.status == "failed"
    
    
def test_stage_outcome_result_dict():
    result = AgentResult(
        status="completed",
        agent="developer",
        task_id="TASK-001",
        data={
            "message": "done",
        },
    )

    outcome = StageOutcome.success(
        WorkflowStage.DEVELOPER,
        result,
    )

    assert outcome.result_dict["status"] == "completed"
    assert outcome.result_dict["agent"] == "developer"
    assert outcome.result_dict["task_id"] == "TASK-001"