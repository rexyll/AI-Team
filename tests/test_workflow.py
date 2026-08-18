from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter
from runtime.workflow import TaskWorkflow


class MockDeveloper:

    role = "developer"

    def __init__(self):
        self.calls = 0
        self.received_feedback = []

    def run(self, task):

        self.calls += 1
        self.received_feedback.append(
            task.context.get("reviewer_feedback")
        )
        
        return {
            "status": "developer_completed",
            "agent": "developer",
            "task_id": task.id,
            "message": (
                f"Developer implementation "
                f"round {self.calls}"
            ),
        }


class MockReviewer:

    role = "reviewer"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def run(self, task):

        self.calls += 1

        if not self.results:
            raise RuntimeError(
                "No more mock review results"
            )

        return self.results.pop(0)


def create_workflow(
    task: Task,
    developer,
    reviewer,
    max_review_rounds=3,
):

    manager = TaskManager([task])

    router = AgentRouter()

    router.register(
        "developer",
        developer,
    )

    router.register(
        "reviewer",
        reviewer,
    )

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        max_review_rounds=max_review_rounds,
    )

    return manager, workflow


def test_developer_completion_requires_review():

    task = Task(
        id="TASK-001",
        title="测试任务",
        description="测试 Developer 完成后的状态",
        role="developer",
        status="ready",
    )

    manager = TaskManager([task])

    manager.mark_running(
        "TASK-001"
    )

    manager.mark_developer_completed(
        "TASK-001",
        {
            "status": "developer_completed",
            "message": "implementation finished",
        },
    )

    assert task.status == "review_pending"


def test_review_approved_completes_task():

    task = Task(
        id="TASK-002",
        title="测试审核通过",
        description="测试 APPROVED",
        role="developer",
        status="review_pending",
    )

    manager = TaskManager([task])

    manager.mark_reviewing(
        "TASK-002"
    )

    review_result = {
        "status": "approved",
        "agent": "reviewer",
        "task_id": "TASK-002",
        "message": "APPROVED",
    }

    manager.mark_review_approved(
        "TASK-002",
        review_result,
    )

    assert task.status == "completed"

    assert task.review_result == review_result


def test_review_revision_required_returns_to_running():

    task = Task(
        id="TASK-003",
        title="测试审核拒绝",
        description="测试 REVISION_REQUIRED",
        role="developer",
        status="review_pending",
    )

    manager = TaskManager([task])

    manager.mark_reviewing(
        "TASK-003"
    )

    review_result = {
        "status": "revision",
        "agent": "reviewer",
        "task_id": "TASK-003",
        "message": (
            "REVISION_REQUIRED\n"
            "缺少测试"
        ),
    }

    manager.mark_review_revision_required(
        "TASK-003",
        review_result,
    )

    assert task.status == "running"

    assert task.review_result == review_result


def test_developer_reviewer_approved_on_first_round():

    task = Task(
        id="TASK-004",
        title="首轮审核通过",
        description="测试完整流程",
        role="developer",
        status="ready",
    )

    developer = MockDeveloper()

    reviewer = MockReviewer(
        [
            {
                "status": "approved",
                "agent": "reviewer",
                "task_id": "TASK-004",
                "message": "APPROVED",
            }
        ]
    )

    manager, workflow = create_workflow(
        task,
        developer,
        reviewer,
    )

    result = workflow.execute(
        "TASK-004"
    )

    assert result.status == "completed"

    assert developer.calls == 1

    assert reviewer.calls == 1

    assert result.review_round == 1

    assert (
        result.review_result["status"]
        == "approved"
    )


def test_developer_reviewer_revision_then_approved():

    task = Task(
        id="TASK-005",
        title="第二轮审核通过",
        description="测试 Developer 修改后再次审核",
        role="developer",
        status="ready",
    )

    developer = MockDeveloper()

    reviewer = MockReviewer(
        [
            {
                "status": "revision",
                "agent": "reviewer",
                "task_id": "TASK-005",
                "message": (
                    "REVISION_REQUIRED\n"
                    "缺少错误处理"
                ),
            },
            {
                "status": "approved",
                "agent": "reviewer",
                "task_id": "TASK-005",
                "message": (
                    "APPROVED\n"
                    "问题已经修复"
                ),
            },
        ]
    )

    manager, workflow = create_workflow(
        task,
        developer,
        reviewer,
    )

    result = workflow.execute(
        "TASK-005"
    )

    assert result.status == "completed"

    assert developer.calls == 2

    assert reviewer.calls == 2

    assert result.review_round == 2

    assert (
        result.review_result["status"]
        == "approved"
    )


def test_review_fails_after_max_rounds():

    task = Task(
        id="TASK-006",
        title="审核次数超限",
        description="测试最大审核次数",
        role="developer",
        status="ready",
    )

    developer = MockDeveloper()

    reviewer = MockReviewer(
        [
            {
                "status": "revision",
                "agent": "reviewer",
                "task_id": "TASK-006",
                "message": "REVISION_REQUIRED",
            },
            {
                "status": "revision",
                "agent": "reviewer",
                "task_id": "TASK-006",
                "message": "REVISION_REQUIRED",
            },
            {
                "status": "revision",
                "agent": "reviewer",
                "task_id": "TASK-006",
                "message": "REVISION_REQUIRED",
            },
        ]
    )

    manager, workflow = create_workflow(
        task,
        developer,
        reviewer,
        max_review_rounds=3,
    )

    result = workflow.execute(
        "TASK-006"
    )

    assert result.status == "failed"

    assert developer.calls == 3

    assert reviewer.calls == 3

    assert result.review_round == 3

    assert (
        result.review_result["status"]
        == "revision"
    )


def test_reviewer_result_is_available_to_next_developer_round():

    task = Task(
        id="TASK-007",
        title="Reviewer 上下文传递",
        description="测试审核结果保存",
        role="developer",
        status="ready",
    )

    developer = MockDeveloper()

    reviewer = MockReviewer(
        [
            {
                "status": "revision",
                "agent": "reviewer",
                "task_id": "TASK-007",
                "message": (
                    "REVISION_REQUIRED\n"
                    "需要增加单元测试"
                ),
            },
            {
                "status": "approved",
                "agent": "reviewer",
                "task_id": "TASK-007",
                "message": "APPROVED",
            },
        ]
    )

    manager, workflow = create_workflow(
        task,
        developer,
        reviewer,
    )

    result = workflow.execute(
        "TASK-007"
    )

    assert result.status == "completed"

    assert result.review_round == 2

    assert developer.calls == 2

    assert developer.received_feedback[0] is None

    assert (
        "需要增加单元测试"
        in result.context["reviewer_feedback"]["message"]
    )