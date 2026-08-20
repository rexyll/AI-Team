from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from runtime.llm.base import BaseLLM


class MockLLM(BaseLLM):
    """Deterministic in-memory LLM implementation for tests and local runs."""

    def __init__(
        self,
        response: str = "MOCK_RESPONSE",
        *,
        responses: Iterable[str] | None = None,
    ) -> None:
        if not isinstance(response, str):
            raise TypeError("MockLLM response must be a string")

        self.response = response
        self._responses = list(responses or [])
        if not all(isinstance(item, str) for item in self._responses):
            raise TypeError("MockLLM responses must contain only strings")

        self.calls: list[dict[str, Any]] = []

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

    @property
    def remaining_responses(self) -> int:
        return len(self._responses)

    def reset(self) -> None:
        self.calls.clear()
