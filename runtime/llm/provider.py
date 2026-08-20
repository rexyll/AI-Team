from __future__ import annotations

from typing import Any

from config.model import AGNES_MODEL, client
from runtime.llm.base import BaseLLM


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
