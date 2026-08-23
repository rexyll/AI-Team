from __future__ import annotations

from typing import Any

from config.model import AGNES_MODEL, client
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall


class ProviderLLM(BaseLLM):
    """BaseLLM adapter for the project's OpenAI-compatible provider client."""

    def __init__(
        self,
        *,
        model: str = AGNES_MODEL,
        client_instance: Any = client,
    ) -> None:
        if not isinstance(model, str):
            raise TypeError("ProviderLLM model must be a string")
        if not model.strip():
            raise ValueError("ProviderLLM model must be a non-empty string")
        if client_instance is None:
            raise ValueError("ProviderLLM client_instance is required")

        self.model = model
        self.client = client_instance

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        if not isinstance(prompt, str):
            raise TypeError("ProviderLLM prompt must be a string")
        if not isinstance(system_prompt, str):
            raise TypeError("ProviderLLM system_prompt must be a string")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content or ""

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Native tool-calling completion mapped to the neutral LLMResponse."""
        if not isinstance(messages, list) or not messages:
            raise TypeError("ProviderLLM messages must be a non-empty list")

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = tool_choice

        response = self.client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls = tuple(
            LLMToolCall(
                call_id=tool_call.id,
                name=tool_call.function.name,
                arguments=tool_call.function.arguments,
            )
            for tool_call in raw_tool_calls
        )

        return LLMResponse(content=message.content, tool_calls=tool_calls)
