from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent as RuntimeTesterAgent
from runtime.llm.mock import MockLLM
from runtime.task import Task


def _task() -> Task:
    return Task(
        id="TASK-CTX-001",
        title="Context migration",
        description="Verify AgentContext migration.",
        role="developer",
        status="reviewing",
        review_round=2,
        result={
            "status": "completed",
            "agent": "developer",
            "task_id": "TASK-CTX-001",
            "message": "implemented",
            "data": {
                "summary": "implemented",
                "tests": ["pytest -q -> 10 passed"],
                "files_changed": ["src/example.py"],
            },
        },
        test_result={
            "status": "passed",
            "message": "TEST_PASSED",
            "data": {"decision": "passed"},
        },
        review_result={
            "status": "revision",
            "message": "REVISION_REQUIRED",
        },
        context={
            "feature_flag": "context-migration",
        },
    )


def test_tester_prompt_consumes_agent_context():
    task = _task()
    context = RuntimeTesterAgent(llm=MockLLM()).build_context(task)
    prompt = RuntimeTesterAgent._build_prompt(context)

    assert context.task_id in prompt
    assert context.task_title in prompt
    assert "pytest -q -> 10 passed" in prompt
    assert "src/example.py" in prompt


def test_reviewer_prompt_consumes_agent_context():
    task = _task()
    context = ReviewerAgent(llm=MockLLM()).build_context(task)
    prompt = ReviewerAgent._build_prompt(context)

    assert context.task_id in prompt
    assert context.task_title in prompt
    assert "pytest -q -> 10 passed" in prompt
    assert "TEST_PASSED" in prompt
    assert "REVISION_REQUIRED" in prompt
    assert "context-migration" in prompt
    assert "review_round=2" in prompt


def test_tester_run_uses_agent_context_and_preserves_result():
    task = _task()
    llm = MockLLM("TEST_PASSED\nEvidence is sufficient.")

    result = RuntimeTesterAgent(llm=llm).run(task)

    assert result.status == "passed"
    assert result.agent == "tester"
    assert result.task_id == "TASK-CTX-001"
    assert result.data["tests"] == ["pytest -q -> 10 passed"]
    assert result.data["files_changed"] == ["src/example.py"]
    assert len(llm.calls) == 1


def test_reviewer_run_uses_agent_context_and_preserves_result():
    task = _task()
    llm = MockLLM("APPROVED\nAll requirements are satisfied.")

    result = ReviewerAgent(llm=llm).run(task)

    assert result.status == "approved"
    assert result.agent == "reviewer"
    assert result.task_id == "TASK-CTX-001"
    assert result.data["tester_status"] == "passed"
    assert result.data["tests"] == ["pytest -q -> 10 passed"]
    assert result.data["files_changed"] == ["src/example.py"]
    assert len(llm.calls) == 1
