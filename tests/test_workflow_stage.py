from runtime.workflow import (
    WorkflowStage,
    StageOutcome,
)
from .test_workflow import (
    MockDeveloper,
    MockTester,
    MockReviewer,
    create_workflow,
)

from runtime.task import Task

def test_stage_outcome_developer():
    outcome = StageOutcome(
        stage=WorkflowStage.DEVELOPER,
        status="completed",
        result={
            "status": "completed",
            "message": "implementation complete",
        },
    )

    assert outcome.stage == WorkflowStage.DEVELOPER
    assert outcome.status == "completed"
    assert outcome.result["status"] == "completed"
    

def test_stage_outcome_tester():
    outcome = StageOutcome(
        stage=WorkflowStage.TESTER,
        status="passed",
        result={
            "status": "passed",
        },
    )

    assert outcome.stage == WorkflowStage.TESTER
    assert outcome.status == "passed"
    
    
def test_stage_outcome_reviewer():
    outcome = StageOutcome(
        stage=WorkflowStage.REVIEWER,
        status="revision",
        result={
            "status": "revision",
        },
    )

    assert outcome.stage == WorkflowStage.REVIEWER
    assert outcome.status == "revision"
    
    
def test_run_developer_returns_stage_outcome():
    task = Task(
        id="TASK-DEV-001",
        title="Developer stage test",
        description="Test developer stage outcome",
        role="developer",
        status="running",
    )

    manager, workflow = create_workflow(
        task,
        MockDeveloper(),
        MockReviewer(),
    )

    original_status = task.status
    original_result = task.result.copy()
    original_error = task.error

    outcome = workflow._run_developer(task)

    assert isinstance(outcome, StageOutcome)
    assert outcome.stage == WorkflowStage.DEVELOPER
    assert outcome.status == "completed"

    assert outcome.result["status"] == "completed"
    assert outcome.result["agent"] == "developer"
    assert outcome.result["task_id"] == task.id

    assert task.status == original_status
    assert task.result == original_result
    assert task.error == original_error


def test_run_tester_returns_stage_outcome():
    task = Task(
        id="TASK-TEST-001",
        title="Tester stage test",
        description="Test tester stage outcome",
        role="developer",
        status="review_pending",
    )

    manager, workflow = create_workflow(
        task,
        MockDeveloper(),
        MockReviewer(),
    )

    original_status = task.status
    original_test_result = task.test_result.copy()
    original_error = task.error

    outcome = workflow._run_tester(task)

    assert isinstance(outcome, StageOutcome)
    assert outcome.stage == WorkflowStage.TESTER
    assert outcome.status == "passed"

    assert outcome.result["status"] == "passed"
    assert outcome.result["agent"] == "tester"
    assert outcome.result["task_id"] == task.id

    assert task.status == original_status
    assert task.test_result == original_test_result
    assert task.error == original_error


def test_run_reviewer_returns_stage_outcome():
    task = Task(
        id="TASK-REVIEW-001",
        title="Reviewer stage test",
        description="Test reviewer stage outcome",
        role="developer",
        status="review_pending",
    )

    manager, workflow = create_workflow(
        task,
        MockDeveloper(),
        MockReviewer(),
    )

    original_status = task.status
    original_review_result = task.review_result.copy()
    original_review_history = list(task.review_history)
    original_review_round = task.review_round
    original_error = task.error

    outcome = workflow._run_reviewer(task)

    assert isinstance(outcome, StageOutcome)
    assert outcome.stage == WorkflowStage.REVIEWER
    assert outcome.status == "approved"

    assert outcome.result["status"] == "approved"
    assert outcome.result["agent"] == "reviewer"
    assert outcome.result["task_id"] == task.id

    assert task.status == original_status
    assert task.review_result == original_review_result
    assert task.review_history == original_review_history
    assert task.review_round == original_review_round
    assert task.error == original_error