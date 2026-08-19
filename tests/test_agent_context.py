from runtime.task import Task


def test_context_builder_builds_agent_context():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
    )

    context = ContextBuilder().build(task)

    assert context.task_id == "TASK-001"
    assert context.task_title == "demo"
    assert context.task_description == "test task"
    assert context.role == "developer"
    assert context.status == "running"
    
    
def test_context_contains_tester_feedback():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
    )

    task.test_result = {
        "status": "failed",
        "agent": "tester",
        "task_id": "TASK-001",
        "message": "missing boundary tests",
    }

    context = ContextBuilder().build(task)

    assert context.tester_feedback["status"] == "failed"
    assert context.tester_feedback["message"] == "missing boundary tests"
    
    
    
def test_context_contains_reviewer_feedback():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="revision",
    )

    task.review_result = {
        "status": "revision",
        "agent": "reviewer",
        "task_id": "TASK-001",
        "message": "improve error handling",
    }

    context = ContextBuilder().build(task)

    assert context.reviewer_feedback["status"] == "revision"
    assert (
        context.reviewer_feedback["message"]
        == "improve error handling"
    )