from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall


class MockLLM(BaseLLM):
    """Deterministic in-memory LLM implementation for tests and local runs.

    ``generate()`` replays fixed text responses. ``generate_with_tools()``
    optionally replays a scripted sequence of turns via ``tool_script``:
    each entry is either a plain string (final text content) or a dict of
    the form ``{"tool_calls": [{"call_id", "name", "arguments"}],
    "content": str | None}`` describing one tool-calling turn. When the
    script is exhausted (or absent), tool-calling turns degrade to a final
    text response, keeping agent loops deterministic and network-free.
    """

    def __init__(
        self,
        response: str = "MOCK_RESPONSE",
        *,
        responses: Iterable[str] | None = None,
        tool_script: Iterable[Any] | None = None,
    ) -> None:
        if not isinstance(response, str):
            raise TypeError("MockLLM response must be a string")

        self.response = response
        self._responses = list(responses or [])
        if not all(isinstance(item, str) for item in self._responses):
            raise TypeError("MockLLM responses must contain only strings")

        self._tool_script = list(tool_script or [])
        for step in self._tool_script:
            self._validate_script_step(step)

        self.calls: list[dict[str, Any]] = []
        self.tool_call_turns: list[dict[str, Any]] = []

    @staticmethod
    def _validate_script_step(step: Any) -> None:
        if isinstance(step, str):
            return
        if not isinstance(step, dict) or not isinstance(step.get("tool_calls"), list):
            raise TypeError(
                "MockLLM tool_script entries must be strings or "
                "{'tool_calls': [...]} dictionaries"
            )
        for item in step["tool_calls"]:
            if not isinstance(item, dict):
                raise TypeError("MockLLM tool_call entries must be dictionaries")
            for key in ("call_id", "name", "arguments"):
                if not isinstance(item.get(key), str) or not item[key]:
                    raise TypeError(
                        f"MockLLM tool_call entry requires a non-empty string {key!r}"
                    )

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        if not isinstance(prompt, str):
            raise TypeError("MockLLM prompt must be a string")
        if not isinstance(system_prompt, str):
            raise TypeError("MockLLM system_prompt must be a string")
        if not isinstance(temperature, (int, float)):
            raise TypeError("MockLLM temperature must be numeric")
        if not isinstance(max_tokens, int):
            raise TypeError("MockLLM max_tokens must be an integer")

        self.calls.append(
            deepcopy(
                {
                    "prompt": prompt,
                    "system_prompt": system_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
        )

        if self._responses:
            return self._responses.pop(0)
        return self.response

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        if not isinstance(messages, list):
            raise TypeError("MockLLM messages must be a list")

        self.tool_call_turns.append(
            deepcopy(
                {
                    "message_count": len(messages),
                    "tool_count": len(tools or []),
                    "tool_choice": tool_choice,
                }
            )
        )

        if self._tool_script:
            step = self._tool_script.pop(0)
            if isinstance(step, str):
                return LLMResponse(content=step)

            tool_calls = tuple(
                LLMToolCall(
                    call_id=item["call_id"],
                    name=item["name"],
                    arguments=item["arguments"],
                )
                for item in step["tool_calls"]
            )
            content = step.get("content")
            return LLMResponse(
                content=content if isinstance(content, str) else None,
                tool_calls=tool_calls,
            )

        return LLMResponse(content=self.generate(self._last_user_prompt(messages)))

    @staticmethod
    def _last_user_prompt(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content
        return ""

    @property
    def remaining_responses(self) -> int:
        return len(self._responses)

    @property
    def remaining_tool_script_steps(self) -> int:
        return len(self._tool_script)

    def reset(self) -> None:
        self.calls.clear()
        self.tool_call_turns.clear()
