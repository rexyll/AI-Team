from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.agent_result import AgentResult
from runtime.workflow import (
    TaskWorkflow,
    WorkflowStage,
    StageOutcome,
)


class MockDeveloper:
    role = "developer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1

        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implementation complete",
        }


class MockTester:
    role = "tester"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1

        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "all tests passed",
        }


class MockReviewer:
    role = "reviewer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1

        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "LGTM",
        }


def create_stage_workflow(task):
    manager = TaskManager([task])

    developer = MockDeveloper()
    tester = MockTester()
    reviewer = MockReviewer()

    router = AgentRouter()

    router.register(
        "developer",
        developer,
    )

    router.register(
        "tester",
        tester,
    )

    router.register(
        "reviewer",
        reviewer,
    )

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
    )

    return manager, workflow


def test_run_developer_returns_stage_outcome():
    task = Task(
        id="TASK-DEV-001",
        title="Developer stage test",
        description="Test developer stage outcome",
        role="developer",
        status="running",
    )

    manager, workflow = create_stage_workflow(task)

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
    assert outcome.result["message"] == "implementation complete"

    # _run_developer() 只负责执行 Agent，
    # 不应该直接修改 Task 生命周期。
    assert task.status == original_status
    assert task.result == original_result
    assert task.error == original_error

    assert workflow.developer.calls == 1


def test_run_tester_returns_stage_outcome():
    task = Task(
        id="TASK-TEST-001",
        title="Tester stage test",
        description="Test tester stage outcome",
        role="developer",
        status="review_pending",
    )

    manager, workflow = create_stage_workflow(task)

    original_status = task.status
    original_test_result = task.test_result.copy()
    original_test_history = list(task.test_history)
    original_error = task.error

    outcome = workflow._run_tester(task)

    assert isinstance(outcome, StageOutcome)

    assert outcome.stage == WorkflowStage.TESTER
    assert outcome.status == "passed"

    assert outcome.result["status"] == "passed"
    assert outcome.result["agent"] == "tester"
    assert outcome.result["task_id"] == task.id
    assert outcome.result["message"] == "all tests passed"

    # _run_tester() 只负责执行 Tester，
    # 不应该直接修改 Task 生命周期。
    assert task.status == original_status
    assert task.test_result == original_test_result
    assert task.test_history == original_test_history
    assert task.error == original_error

    assert workflow.tester.calls == 1


def test_run_reviewer_returns_stage_outcome():
    task = Task(
        id="TASK-REVIEW-001",
        title="Reviewer stage test",
        description="Test reviewer stage outcome",
        role="developer",
        status="review_pending",
    )

    manager, workflow = create_stage_workflow(task)

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
    assert outcome.result["message"] == "LGTM"

    # _run_reviewer() 只负责执行 Reviewer，
    # 不应该直接修改 Task 生命周期。
    assert task.status == original_status
    assert task.review_result == original_review_result
    assert task.review_history == original_review_history
    assert task.review_round == original_review_round
    assert task.error == original_error

    assert workflow.reviewer.calls == 1


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
    
    
def test_run_developer_returns_agent_result_inside_stage_outcome():
    task = Task(
        id="TASK-DEV-001",
        title="Developer stage test",
        description="Test developer stage outcome",
        role="developer",
        status="running",
    )

    manager, workflow = create_stage_workflow(task)

    original_status = task.status
    original_result = task.result.copy()
    original_error = task.error

    outcome = workflow._run_developer(task)

    assert isinstance(outcome, StageOutcome)

    assert outcome.stage == WorkflowStage.DEVELOPER
    assert outcome.status == "completed"

    # StageOutcome.result 必须是 canonical AgentResult
    assert isinstance(outcome.result, AgentResult)

    assert outcome.result.status == "completed"
    assert outcome.result.agent == "developer"
    assert outcome.result.task_id == task.id
    assert outcome.result.message == "implementation complete"
    assert outcome.result.data == {}

    # result_dict 是 AgentResult 的 canonical dictionary
    assert outcome.result_dict == {
        "status": "completed",
        "agent": "developer",
        "task_id": task.id,
        "message": "implementation complete",
        "data": {},
    }

    # _run_developer() 只负责执行 Agent，
    # 不应该直接修改 Task 生命周期。
    assert task.status == original_status
    assert task.result == original_result
    assert task.error == original_error

    assert workflow.developer.calls == 1
    
    
    
def test_run_tester_returns_agent_result_inside_stage_outcome():
    task = Task(
        id="TASK-TEST-001",
        title="Tester stage test",
        description="Test tester stage outcome",
        role="developer",
        status="review_pending",
    )

    manager, workflow = create_stage_workflow(task)

    original_status = task.status
    original_test_result = task.test_result.copy()
    original_test_history = list(task.test_history)
    original_error = task.error

    outcome = workflow._run_tester(task)

    assert isinstance(outcome, StageOutcome)

    assert outcome.stage == WorkflowStage.TESTER
    assert outcome.status == "passed"

    # StageOutcome.result 必须是 canonical AgentResult
    assert isinstance(outcome.result, AgentResult)

    assert outcome.result.status == "passed"
    assert outcome.result.agent == "tester"
    assert outcome.result.task_id == task.id
    assert outcome.result.message == "all tests passed"
    assert outcome.result.data == {}

    # result_dict 是 AgentResult 的 canonical dictionary
    assert outcome.result_dict == {
        "status": "passed",
        "agent": "tester",
        "task_id": task.id,
        "message": "all tests passed",
        "data": {},
    }

    # _run_tester() 只负责执行 Tester，
    # 不应该直接修改 Task 生命周期。
    assert task.status == original_status
    assert task.test_result == original_test_result
    assert task.test_history == original_test_history
    assert task.error == original_error

    assert workflow.tester.calls == 1
    
    
def test_run_reviewer_returns_agent_result_inside_stage_outcome():
    task = Task(
        id="TASK-REVIEW-001",
        title="Reviewer stage test",
        description="Test reviewer stage outcome",
        role="developer",
        status="review_pending",
    )

    manager, workflow = create_stage_workflow(task)

    original_status = task.status
    original_review_result = task.review_result.copy()
    original_review_history = list(task.review_history)
    original_review_round = task.review_round
    original_error = task.error

    outcome = workflow._run_reviewer(task)

    assert isinstance(outcome, StageOutcome)

    assert outcome.stage == WorkflowStage.REVIEWER
    assert outcome.status == "approved"

    # StageOutcome.result 必须是 canonical AgentResult
    assert isinstance(outcome.result, AgentResult)

    assert outcome.result.status == "approved"
    assert outcome.result.agent == "reviewer"
    assert outcome.result.task_id == task.id
    assert outcome.result.message == "LGTM"
    assert outcome.result.data == {}

    # result_dict 是 AgentResult 的 canonical dictionary
    assert outcome.result_dict == {
        "status": "approved",
        "agent": "reviewer",
        "task_id": task.id,
        "message": "LGTM",
        "data": {},
    }

    # _run_reviewer() 只负责执行 Reviewer，
    # 不应该直接修改 Task 生命周期。
    assert task.status == original_status
    assert task.review_result == original_review_result
    assert task.review_history == original_review_history
    assert task.review_round == original_review_round
    assert task.error == original_error

    assert workflow.reviewer.calls == 1