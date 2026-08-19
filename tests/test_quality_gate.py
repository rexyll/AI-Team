from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class FakeDeveloper:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = 0

    def run(self, task):
        self.calls += 1

        if self.results:
            return self.results.pop(0)

        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "development completed",
        }


class FakeTester:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = 0

    def run(self, task):
        self.calls += 1

        if self.results:
            return self.results.pop(0)

        raise AssertionError(
            "FakeTester has no scripted result for this test"
        )


class FakeReviewer:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = 0

    def run(self, task):
        self.calls += 1

        if self.results:
            return self.results.pop(0)

        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED",
        }


class DummyAgentRouter:
    def route(self, role):
        raise AssertionError(
            "Quality gate tests should not depend on AgentRouter routing."
        )


def create_task():
    return Task(
        id="TASK-QG-001",
        title="quality gate",
        description="test developer tester reviewer workflow",
        role="developer",
        status="ready",
    )


def create_workflow(developer, tester, reviewer):
    task = create_task()
    manager = TaskManager([task])

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=DummyAgentRouter(),
    )

    return task, workflow


def test_developer_must_pass_tester_before_reviewer():
    developer = FakeDeveloper()
    tester = FakeTester(
        [
            {
                "status": "passed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "TEST_PASSED",
            }
        ]
    )
    reviewer = FakeReviewer()

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"

    assert developer.calls == 1
    assert tester.calls == 1
    assert reviewer.calls == 1


def test_tester_pass_allows_reviewer():
    developer = FakeDeveloper()

    tester = FakeTester(
        [
            {
                "status": "passed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "TEST_PASSED",
            }
        ]
    )

    reviewer = FakeReviewer(
        [
            {
                "status": "approved",
                "agent": "reviewer",
                "task_id": "TASK-QG-001",
                "message": "APPROVED",
            }
        ]
    )

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert tester.calls == 1
    assert reviewer.calls == 1


def test_tester_failure_requires_developer_revision_before_reviewer():
    developer = FakeDeveloper()

    tester = FakeTester(
        [
            {
                "status": "failed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "缺少边界测试",
            },
            {
                "status": "passed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "TEST_PASSED",
            },
        ]
    )

    reviewer = FakeReviewer()

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"

    # Tester 第一次失败后，Developer 必须重新执行
    assert developer.calls == 2

    # Tester 必须重新测试
    assert tester.calls == 2

    # 最终只有 Tester PASSED 后才能进入 Reviewer
    assert reviewer.calls == 1

    # Tester 的失败反馈必须被保存
    assert len(task.test_history) == 2
    assert task.test_history[0]["status"] == "failed"
    assert task.test_history[1]["status"] == "passed"


def test_tester_failure_feedback_is_available_to_next_developer_round():
    developer = FakeDeveloper()

    tester = FakeTester(
        [
            {
                "status": "failed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "需要增加单元测试",
            },
            {
                "status": "passed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "TEST_PASSED",
            },
        ]
    )

    reviewer = FakeReviewer()

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"

    assert developer.calls == 2
    assert tester.calls == 2

    assert (
        "tester_feedback" in result.context
        or "test_result" in result.context
    )


def test_tester_exception_fails_task():
    class FailingTester:
        def run(self, task):
            raise RuntimeError("tester crashed")

    developer = FakeDeveloper()
    tester = FailingTester()
    reviewer = FakeReviewer()

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    try:
        workflow.execute(task.id)
    except RuntimeError:
        pass

    assert task.status == "failed"
    assert reviewer.calls == 0


def test_invalid_tester_result_fails_task():
    class InvalidTester:
        def run(self, task):
            return {
                "status": "invalid",
                "agent": "tester",
                "task_id": task.id,
                "message": "invalid result",
            }

    developer = FakeDeveloper()
    tester = InvalidTester()
    reviewer = FakeReviewer()

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    result = workflow.execute(task.id)

    assert result.status == "failed"
    assert reviewer.calls == 0
    
    
def test_tester_failed_requires_developer_revision():
    developer = FakeDeveloper()

    tester = FakeTester(
        [
            {
                "status": "failed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "需要修复边界条件",
            },
            {
                "status": "passed",
                "agent": "tester",
                "task_id": "TASK-QG-001",
                "message": "TEST_PASSED",
            },
        ]
    )

    reviewer = FakeReviewer()

    task, workflow = create_workflow(
        developer,
        tester,
        reviewer,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert len(task.test_history) == 2