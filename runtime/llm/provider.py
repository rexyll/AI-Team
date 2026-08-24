from __future__ import annotations

from typing import Any

from config.model import AGNES_MODEL, get_provider_profile
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall


class ProviderLLM(BaseLLM):
    """BaseLLM adapter for OpenAI-compatible provider clients.

    Supports multiple provider profiles (see ``config.model``): pass an
    explicit ``model`` and/or ``provider_profile`` name; when omitted,
    both resolve to the Agnes defaults for backward compatibility. The
    underlying client is resolved lazily on first completion request, so
    construction never touches provider credentials.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        provider_profile: str | None = None,
        client_instance: Any = None,
    ) -> None:
        if model is not None and provider_profile is None:
            # Legacy single-provider form: bare model means Agnes default.
            resolved_model = model
            resolved_profile = "agnes"
        else:
            profile = get_provider_profile(provider_profile)
            resolved_profile = profile.name
            resolved_model = model if model is not None else profile.default_model

        if not isinstance(resolved_model, str):
            raise TypeError("ProviderLLM model must be a string")
        if not resolved_model.strip():
            raise ValueError("ProviderLLM model must be a non-empty string")

        self.provider_profile = resolved_profile
        self.model = resolved_model
        self._client: Any = client_instance

    @property
    def client(self) -> Any:
        """Resolve the provider client lazily via ``config.get_client_for``."""
        if self._client is None:
            from config.model import get_client_for

            self._client = get_client_for(self.provider_profile)
        return self._client

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
