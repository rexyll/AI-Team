from __future__ import annotations

from agents.reviewer import (
    DEFAULT_REVIEWER_MAX_DEVELOPER_RESULT_CHARS,
    ReviewerAgent,
)
from runtime.llm.mock import MockLLM
from runtime.task import Task


def _task_with_large_report(size: int = 100_000) -> Task:
    return Task(
        id="TASK-REVIEW-BUDGET-001",
        title="large review payload",
        description="Review the generated implementation and tests.",
        role="reviewer",
        status="reviewing",
        result={
            "status": "completed",
            "agent": "developer",
            "task_id": "TASK-REVIEW-BUDGET-001",
            "message": "implemented",
            "data": {
                "files_changed": ["app.py", "tests/test_app.py"],
                "tests": ["pytest -q -> 17 passed"],
                "validation": {"test_command_count": 1},
                "report": "HEADER-EVIDENCE\n" + ("x" * size) + "\nTAIL-EVIDENCE",
            },
        },
        test_result={
            "status": "passed",
            "message": "TEST_PASSED",
        },
    )


def test_reviewer_bounds_large_developer_result_without_losing_evidence():
    llm = MockLLM("APPROVED\nEvidence is sufficient.")
    agent = ReviewerAgent(llm=llm)

    result = agent.run(_task_with_large_report())

    assert result.status == "approved"
    prompt = llm.calls[0]["prompt"]
    assert len(prompt) < DEFAULT_REVIEWER_MAX_DEVELOPER_RESULT_CHARS + 20_000
    assert "HEADER-EVIDENCE" in prompt
    assert "TAIL-EVIDENCE" in prompt
    assert "app.py" in prompt
    assert "pytest -q -> 17 passed" in prompt
    assert "...[truncated " in prompt


def test_reviewer_budget_can_be_configured(monkeypatch):
    monkeypatch.setenv("REVIEWER_MAX_DEVELOPER_RESULT_CHARS", "4000")
    llm = MockLLM("APPROVED")
    agent = ReviewerAgent(llm=llm)

    agent.run(_task_with_large_report())

    prompt = llm.calls[0]["prompt"]
    developer_section = prompt.split("DEVELOPER RESULT (BOUNDED)", 1)[1].split(
        "TESTER RESULT", 1
    )[0]
    assert len(developer_section) <= 4_500
