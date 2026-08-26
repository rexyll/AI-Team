from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall


class _ScriptedLLM(BaseLLM):
    """Minimal BaseLLM-compatible multi-turn tool caller for this contract."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self.round = 0

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        return "unused"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto") -> LLMResponse:
        self.calls.append(messages)
        self.round += 1
        if self.round >= 8:
            return LLMResponse(content="completed")
        return LLMResponse(
            content="tool reasoning " * 80,
            tool_calls=(
                LLMToolCall(
                    call_id=f"call-{self.round}",
                    name="read_file",
                    arguments="{}",
                ),
            ),
        )


class _Agent(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def run(self, task):
        raise NotImplementedError


def test_repeated_tool_history_stays_within_context_budget(monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_MAX_PROMPT_CHARS", "4000")
    monkeypatch.setenv("AI_TEAM_MAX_INPUT_TOKENS_PER_CALL", "2000")
    llm = _ScriptedLLM()
    agent = _Agent(llm=llm)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "stable developer system instructions"},
        {"role": "user", "content": "Implement the requested change and verify it."},
    ]

    for _ in range(8):
        response = agent._generate_with_tools(messages)
        if not response.tool_calls:
            break
        messages.append(
            {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in response.tool_calls
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": response.tool_calls[0].call_id,
                "content": "large tool output " * 400,
            }
        )

    metrics = agent.metrics_snapshot()

    assert metrics.llm_calls == 8
    assert metrics.tool_calls == 7
    assert metrics.max_prompt_chars <= 4000
    assert metrics.max_input_tokens_per_call <= 2000
    assert metrics.context_growth_ratio < 3.0
    assert len(llm.calls) == 8
    assert all(
        sum(len(str(message.get("content") or "")) for message in call) <= 4000
        for call in llm.calls
    )
