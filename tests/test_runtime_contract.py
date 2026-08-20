import pytest

from runtime.agent_result import AgentResult
from runtime.runtime_contract import (
    ContractError,
    validate_agent_result_payload,
    validate_context_contract,
    validate_stage_outcome_contract,
    validate_task_contract,
)
from runtime.task import Task
from runtime.workflow import (
    StageOutcome,
    WorkflowStage,
)


def make_task():
    return Task(
        id="TASK-001",
        title="测试任务",
        description="测试 Runtime Contract",
        role="developer",
    )


def test_task_contract_accepts_valid_task():
    task = make_task()

    validate_task_contract(task)


def test_task_contract_rejects_invalid_id():
    task = make_task()
    task.id = ""

    with pytest.raises(ContractError):
        validate_task_contract(task)


def test_task_contract_rejects_invalid_context():
    task = make_task()
    task.context = []

    with pytest.raises(ContractError):
        validate_task_contract(task)


def test_task_contract_rejects_negative_review_round():
    task = make_task()
    task.review_round = -1

    with pytest.raises(ContractError):
        validate_task_contract(task)


def test_context_contract_accepts_empty_context():
    validate_context_contract({})


def test_context_contract_accepts_reserved_context():
    validate_context_contract(
        {
            "dependencies": {},
            "tester_feedback": {
                "status": "failed",
            },
            "reviewer_feedback": {
                "status": "revision",
            },
        }
    )


def test_agent_result_contract_accepts_agent_result():
    result = AgentResult(
        status="completed",
        data={
            "message": "done",
        },
    )

    validate_agent_result_payload(result)


def test_agent_result_contract_accepts_dict():
    validate_agent_result_payload(
        {
            "status": "completed",
            "data": {},
        }
    )


def test_agent_result_contract_rejects_missing_status():
    with pytest.raises(ContractError):
        validate_agent_result_payload(
            {
                "data": {},
            }
        )


def test_agent_result_contract_rejects_invalid_data():
    with pytest.raises(ContractError):
        validate_agent_result_payload(
            {
                "status": "completed",
                "data": [],
            }
        )


def test_stage_outcome_contract_accepts_valid_outcome():
    result = AgentResult(
        status="completed",
        data={},
    )

    outcome = StageOutcome(
        stage=WorkflowStage.DEVELOPER,
        status="completed",
        result=result,
    )

    validate_stage_outcome_contract(outcome)


def test_stage_outcome_contract_accepts_exception():
    outcome = StageOutcome(
        stage=WorkflowStage.DEVELOPER,
        status="failed",
        result=None,
        exception=RuntimeError("boom"),
    )

    validate_stage_outcome_contract(outcome)


def test_stage_outcome_contract_rejects_invalid_exception():
    with pytest.raises(TypeError):
        StageOutcome(
            stage=WorkflowStage.DEVELOPER,
            status="failed",
            result=None,
            exception="boom",
        )
        
        
def test_workflow_contract_chain():
    task = make_task()

    validate_task_contract(task)

    result = AgentResult(
        status="completed",
        data={
            "message": "developer completed",
        },
    )

    outcome = StageOutcome(
        stage=WorkflowStage.DEVELOPER,
        status=result.status,
        result=result,
    )

    validate_agent_result_payload(result)
    validate_stage_outcome_contract(outcome)