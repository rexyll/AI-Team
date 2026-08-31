from __future__ import annotations

import os
import time
from typing import Any

from config.model import get_provider_profile
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall


RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _status_code_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    message = str(exc)
    for code in sorted(RETRYABLE_STATUS_CODES):
        if f"Error code: {code}" in message:
            return code
    return None


def _message_role(message: Any) -> Any:
    return message.get("role") if isinstance(message, dict) else None


class ProviderLLM(BaseLLM):
    """BaseLLM adapter for OpenAI-compatible provider clients.

    Provider and model selection is environment-driven. Tests and callers
    may inject a client directly; in that case no provider configuration is
    required because the client is already supplied by the caller.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        provider_profile: str | None = None,
        client_instance: Any = None,
    ) -> None:
        if client_instance is not None and provider_profile is None:
            resolved_profile = "injected"
            resolved_model = model or os.getenv("DEFAULT_MODEL", "").strip()
            if not resolved_model:
                raise ValueError(
                    "model is required when using an injected ProviderLLM client"
                )
        else:
            profile = get_provider_profile(provider_profile)
            resolved_profile = profile.name
            resolved_model = (model or profile.default_model).strip()
            if not resolved_model:
                resolved_model = os.getenv("DEFAULT_MODEL", "").strip()
            if not resolved_model:
                raise ValueError(
                    f"No model configured for provider '{resolved_profile}'"
                )

        if not isinstance(resolved_model, str) or not resolved_model.strip():
            raise TypeError("ProviderLLM model must be a non-empty string")

        self.provider_profile = resolved_profile
        self.model = resolved_model
        self._client: Any = client_instance

    @property
    def client(self) -> Any:
        if self._client is None:
            from config.model import get_client_for

            self._client = get_client_for(self.provider_profile)
        return self._client

    def _max_attempts(self) -> int:
        try:
            return max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "4")))
        except ValueError:
            return 4

    def _backoff_seconds(self, attempt: int, exc: BaseException | None) -> float:
        base = 2.0
        try:
            base = float(os.getenv("LLM_BACKOFF_SECONDS", "2"))
        except ValueError:
            pass

        response = getattr(exc, "response", None) if exc is not None else None
        headers = getattr(response, "headers", None)
        raw = None
        if headers is not None and hasattr(headers, "get"):
            try:
                raw = headers.get("retry-after") or headers.get("Retry-After")
            except Exception:
                raw = None
        try:
            hint = float(raw)
        except (TypeError, ValueError):
            hint = 0.0

        return max(base * (2 ** (attempt - 1)), hint)

    @staticmethod
    def _has_content_or_tool_calls(response: Any) -> bool:
        try:
            message = response.choices[0].message
        except (AttributeError, IndexError, TypeError):
            return False
        content = getattr(message, "content", None)
        raw_calls = getattr(message, "tool_calls", None)
        return bool(content and str(content).strip()) or bool(raw_calls)

    @staticmethod
    def _normalized_content(content: Any) -> str:
        if content is None:
            return ""
        text = str(content)
        return "" if not text.strip() else text

    @staticmethod
    def _usage_of(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}

        def value(name: str) -> int:
            raw = usage.get(name, 0) if isinstance(usage, dict) else getattr(usage, name, 0)
            try:
                return max(0, int(raw or 0))
            except (TypeError, ValueError):
                return 0

        prompt_tokens = value("prompt_tokens")
        completion_tokens = value("completion_tokens")
        total_tokens = value("total_tokens")
        if not total_tokens:
            total_tokens = prompt_tokens + completion_tokens
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    def _post_chat(self, **kwargs: Any):
        max_attempts = self._max_attempts()
        http_attempt = 0
        empty_attempt = 0

        while True:
            try:
                response = self.client.chat.completions.create(**kwargs)

                if not self._has_content_or_tool_calls(response):
                    empty_attempt += 1
                    if empty_attempt >= max_attempts:
                        return response
                    wait = self._backoff_seconds(empty_attempt, None)
                    print(
                        f"[LLM] {self.provider_profile}/{self.model} "
                        f"empty response; retrying ({empty_attempt}/{max_attempts})"
                    )
                    time.sleep(wait)
                    continue

                return response

            except Exception as exc:
                code = _status_code_of(exc)
                http_attempt += 1
                if code not in RETRYABLE_STATUS_CODES or http_attempt >= max_attempts:
                    raise
                wait = self._backoff_seconds(http_attempt, exc)
                print(
                    f"[LLM] {self.provider_profile}/{self.model} transient {code}; "
                    f"retry {http_attempt}/{max_attempts - 1} in {wait:.0f}s"
                )
                time.sleep(wait)

    @staticmethod
    def _needs_user_continuation(messages: list[dict[str, Any]]) -> bool:
        return bool(messages) and _message_role(messages[-1]) == "tool"

    def _prepare_tool_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep Agnes tool continuation compatible without introducing a new instruction.

        The Agnes-compatible gateway requires a user message after tool results.
        Reuse the original user query rather than inventing a fresh control
        instruction, so the model sees the same task intent and only gains the
        message role needed by the provider's chat template.
        """
        prepared = [dict(message) for message in messages]
        if self.provider_profile == "agnes" and self._needs_user_continuation(prepared):
            original_user = next(
                (message for message in prepared if _message_role(message) == "user"),
                None,
            )
            if original_user is not None:
                prepared.append({"role": "user", "content": original_user.get("content", "")})
        return prepared

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

        response = self._post_chat(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._normalized_content(response.choices[0].message.content)

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        if not isinstance(messages, list) or not messages:
            raise TypeError("ProviderLLM messages must be a non-empty list")

        prepared_messages = self._prepare_tool_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": prepared_messages,
        }
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = tool_choice

        started = time.perf_counter()
        response = self._post_chat(**kwargs)
        latency_seconds = time.perf_counter() - started
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
        return LLMResponse(
            content=self._normalized_content(message.content),
            tool_calls=tool_calls,
            usage=self._usage_of(response),
            latency_seconds=latency_seconds,
        )
