from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.architect import ArchitectAgent
from agents.planner import create_plan
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent as RuntimeTesterAgent
from runtime.llm.mock import MockLLM
from runtime.llm.provider import ProviderLLM
from runtime.task import Task
from security.prompt_injection import UNTRUSTED_CONTENT_POLICY


def _task(**overrides) -> Task:
    values = {
        "id": "TASK-LLM-CONTRACT-001",
        "title": "mock LLM integration",
        "description": "Verify deterministic LLM integration boundaries.",
        "role": "developer",
        "status": "running",
    }
    values.update(overrides)
    return Task(**values)


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=_FakeCompletions(response))


def test_provider_llm_maps_generate_contract_to_openai_compatible_client():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="mocked response"))])
    client = _FakeClient(response)
    llm = ProviderLLM(model="test-model", client_instance=client)
    result = llm.generate("user prompt", system_prompt="system prompt", temperature=0.4, max_tokens=321)
    assert result == "mocked response"
    assert client.chat.completions.calls == [{"model": "test-model", "messages": [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "user prompt"}], "temperature": 0.4, "max_tokens": 321}]


def test_mock_llm_preserves_call_snapshot_and_supports_deterministic_sequence():
    llm = MockLLM(responses=["first", "second"])
    assert llm.generate("p1", system_prompt="s1") == "first"
    assert llm.generate("p2", system_prompt="s2") == "second"
    assert llm.remaining_responses == 0
    assert llm.calls == [{"prompt": "p1", "system_prompt": "s1", "temperature": 0.2, "max_tokens": 4096}, {"prompt": "p2", "system_prompt": "s2", "temperature": 0.2, "max_tokens": 4096}]


def test_mock_llm_can_drive_architect_tester_and_reviewer_without_network():
    architect_llm = MockLLM("ARCHITECTURE_OK")
    tester_llm = MockLLM("TEST_PASSED\nEvidence is sufficient.")
    reviewer_llm = MockLLM("APPROVED\nAll requirements are satisfied.")
    architect_result = ArchitectAgent(llm=architect_llm).run(_task(id="TASK-ARCH-001", role="architect", title="architecture"))
    tester_result = RuntimeTesterAgent(llm=tester_llm).run(_task())
    reviewer_result = ReviewerAgent(llm=reviewer_llm).run(_task(status="reviewing", result={"status": "completed", "agent": "developer", "task_id": "TASK-LLM-CONTRACT-001", "message": "implemented", "data": {"tests": ["pytest -q -> 1 passed"]}}, test_result={"status": "passed", "message": "TEST_PASSED"}))
    assert architect_result.status == "completed"
    assert architect_result.data["architecture"] == "ARCHITECTURE_OK"
    assert tester_result.status == "passed"
    assert reviewer_result.status == "approved"
    assert UNTRUSTED_CONTENT_POLICY in architect_llm.calls[0]["system_prompt"]
    assert UNTRUSTED_CONTENT_POLICY in tester_llm.calls[0]["system_prompt"]
    assert UNTRUSTED_CONTENT_POLICY in reviewer_llm.calls[0]["system_prompt"]


def test_planner_can_be_fully_driven_by_mocked_provider(monkeypatch):
    plan_response = '{"project":"mock-project","summary":"mock summary","tasks":[{"id":"TASK-001","title":"design","description":"design architecture","role":"architect","dependencies":[]}]}'
    calls: list[dict] = []
    llm = MockLLM(plan_response)

    def fake_ask_ai(*, prompt: str, system_prompt: str) -> str:
        calls.append({"prompt": prompt, "system_prompt": system_prompt})
        return llm.generate(prompt, system_prompt=system_prompt)

    monkeypatch.setattr("agents.planner.ask_ai", fake_ask_ai)
    result = create_plan("build a mock project")
    assert result["project"] == "mock-project"
    assert result["tasks"][0]["role"] == "architect"
    assert len(calls) == 1
    assert calls[0]["prompt"]
    assert calls[0]["system_prompt"]
    assert llm.remaining_responses == 0


def test_planner_mock_sequence_exercises_invalid_response_repair_without_network(monkeypatch):
    responses = ["not valid planner output", '{"project":"repaired","summary":"ok","tasks":[{"id":"TASK-001","title":"build","description":"implement","role":"developer","dependencies":[]}]}' ]
    llm = MockLLM(responses=responses)

    def fake_ask_ai(*, prompt: str, system_prompt: str) -> str:
        return llm.generate(prompt, system_prompt=system_prompt)

    monkeypatch.setattr("agents.planner.ask_ai", fake_ask_ai)
    result = create_plan("repairable mock project")
    assert result["project"] == "repaired"
    assert len(llm.calls) == 2
    assert "上一轮 Planner 输出无法通过验证" in llm.calls[1]["prompt"]
    assert llm.remaining_responses == 0


def test_mock_llm_rejects_invalid_generation_arguments():
    llm = MockLLM()
    with pytest.raises(TypeError, match="prompt must be a string"):
        llm.generate(123)  # type: ignore[arg-type]
