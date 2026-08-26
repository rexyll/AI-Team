from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.llm.mock import MockLLM


class _Agent(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def run(self, task):
        raise NotImplementedError


def test_base_agent_generate_uses_compacted_prompt_and_metrics(monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_MAX_PROMPT_CHARS", "500")
    monkeypatch.setenv("AI_TEAM_MAX_INPUT_TOKENS_PER_CALL", "250")
    llm = MockLLM(response="ok")
    agent = _Agent(llm=llm)

    result = agent._generate(
        "request " * 300,
        system_prompt="system",
    )

    assert result == "ok"
    assert len(llm.calls) == 1
    recorded = llm.calls[0]
    assert len(recorded["prompt"]) + len(recorded["system_prompt"]) <= 500

    metrics = agent.metrics_snapshot()
    assert metrics.llm_calls == 1
    assert metrics.tool_calls == 0
    assert metrics.max_prompt_chars <= 500
    assert metrics.max_input_tokens_per_call <= 250


def test_base_agent_tool_boundary_compacts_history_and_counts_tool_calls(monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_MAX_PROMPT_CHARS", "700")
    monkeypatch.setenv("AI_TEAM_MAX_INPUT_TOKENS_PER_CALL", "350")
    llm = MockLLM(
        tool_script=[
            {
                "tool_calls": [
                    {
                        "call_id": "call-1",
                        "name": "read_file",
                        "arguments": "{}",
                    }
                ]
            }
        ]
    )
    agent = _Agent(llm=llm)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "initial request"},
        {"role": "assistant", "content": "old reasoning " * 100},
        {"role": "tool", "tool_call_id": "old", "content": "old output " * 100},
    ]

    response = agent._generate_with_tools(messages)

    assert response.tool_calls[0].call_id == "call-1"
    assert len(llm.tool_call_turns) == 1
    metrics = agent.metrics_snapshot()
    assert metrics.llm_calls == 1
    assert metrics.tool_calls == 1
    assert metrics.max_prompt_chars <= 700
    assert metrics.max_input_tokens_per_call <= 350
