import pytest

from agents.architect import ArchitectAgent, SYSTEM_PROMPT as ARCHITECT_SYSTEM_PROMPT
from agents.reviewer import ReviewerAgent, SYSTEM_PROMPT as REVIEWER_SYSTEM_PROMPT
from agents.tester import TesterAgent as RuntimeTesterAgent, SYSTEM_PROMPT as TESTER_SYSTEM_PROMPT
from runtime.llm.base import BaseLLM
from runtime.llm.mock import MockLLM
from runtime.llm.provider import ProviderLLM
from runtime.task import Task
from security.prompt_injection import UNTRUSTED_CONTENT_POLICY


def make_task(**kwargs) -> Task:
    defaults = {
        "id": "TASK-LLM-001",
        "title": "LLM injection",
        "description": "Verify injectable LLM execution.",
        "role": "developer",
        "status": "running",
    }
    defaults.update(kwargs)
    return Task(**defaults)


def test_base_agent_uses_provider_llm_by_default():
    assert isinstance(ArchitectAgent().llm, ProviderLLM)
    assert isinstance(RuntimeTesterAgent().llm, ProviderLLM)
    assert isinstance(ReviewerAgent().llm, ProviderLLM)


def test_base_agent_rejects_non_base_llm():
    with pytest.raises(TypeError, match="must implement BaseLLM"):
        ArchitectAgent(llm=object())  # type: ignore[arg-type]


def test_architect_accepts_injected_llm():
    llm = MockLLM("architecture")
    agent = ArchitectAgent(llm=llm)
    result = agent.run(make_task(id="TASK-ARCH-LLM-001", title="SQLite Schema", description="Design SQLite schema.", role="architect"))
    assert result.message == "architecture"
    assert len(llm.calls) == 1
    assert llm.calls[0]["system_prompt"].startswith(ARCHITECT_SYSTEM_PROMPT.strip())
    assert UNTRUSTED_CONTENT_POLICY in llm.calls[0]["system_prompt"]
    assert "TASK-ARCH-LLM-001" in llm.calls[0]["prompt"]


def test_tester_accepts_injected_llm():
    llm = MockLLM("TEST_PASSED\nEvidence is sufficient.")
    agent = RuntimeTesterAgent(llm=llm)
    result = agent.run(make_task())
    assert result.status == "passed"
    assert len(llm.calls) == 1
    assert llm.calls[0]["system_prompt"].startswith(TESTER_SYSTEM_PROMPT.strip())
    assert UNTRUSTED_CONTENT_POLICY in llm.calls[0]["system_prompt"]
    assert "TASK-LLM-001" in llm.calls[0]["prompt"]


def test_reviewer_accepts_injected_llm():
    task = make_task(status="reviewing", result={"status": "completed", "agent": "developer", "task_id": "TASK-LLM-001", "message": "implemented", "data": {"tests": ["pytest -q -> 1 passed"]}}, test_result={"status": "passed", "message": "TEST_PASSED"})
    llm = MockLLM("APPROVED\nAll requirements are satisfied.")
    agent = ReviewerAgent(llm=llm)
    result = agent.run(task)
    assert result.status == "approved"
    assert len(llm.calls) == 1
    assert llm.calls[0]["system_prompt"].startswith(REVIEWER_SYSTEM_PROMPT.strip())
    assert UNTRUSTED_CONTENT_POLICY in llm.calls[0]["system_prompt"]
    assert "TASK-LLM-001" in llm.calls[0]["prompt"]


def test_injected_llm_is_shared_execution_dependency():
    llm = MockLLM("response")
    architect = ArchitectAgent(llm=llm)
    tester = RuntimeTesterAgent(llm=llm)
    reviewer = ReviewerAgent(llm=llm)
    assert architect.llm is llm
    assert tester.llm is llm
    assert reviewer.llm is llm
    assert isinstance(llm, BaseLLM)
