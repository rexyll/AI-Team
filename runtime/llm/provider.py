from __future__ import annotations

import os
import time
from typing import Any

from config.model import get_provider_profile
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall


# Transient upstream failures worth retrying with backoff: shared-pool
# rate limits (e.g. OpenRouter free tiers) and gateway blips. Anything
# else (auth, bad request, unknown model) must fail immediately.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _status_code_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status extraction from an SDK exception."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    message = str(exc)
    for code in sorted(RETRYABLE_STATUS_CODES):
        if f"Error code: {code}" in message:
            return code
    return None


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
        # 全环境驱动：model 未显式给出时，从所属 profile 的 MODEL 变量
        # 动态读取（如 OPENROUTER_MODEL / AGNES_MODEL），允许为空——
        # 真正的缺失校验推迟到首次请求时，保持构造零副作用。
        if model is not None and provider_profile is None:
            resolved_model = model
            resolved_profile = "agnes"
        else:
            profile = get_provider_profile(provider_profile)
            resolved_profile = profile.name
            env_model = os.getenv(f"{profile.name.upper()}_MODEL", "")
            resolved_model = (
                model
                if model is not None
                else (env_model or profile.default_model)
            )

        if not isinstance(resolved_model, str):
            raise TypeError("ProviderLLM model must be a string")

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

        # Honor a numeric Retry-After header when the SDK surfaces one.
        response = getattr(exc, "response", None) if exc is not None else None
        headers = getattr(response, "headers", None)
        raw = None
        if headers is not None and hasattr(headers, "get"):
            try:
                raw = headers.get("retry-after") or headers.get("Retry-After")
            except Exception:
                raw = None
        try:
            hint = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            hint = 0.0

        return max(base * (2 ** (attempt - 1)), hint)

    @staticmethod
    def _has_content_or_tool_calls(response: Any) -> bool:
        """Return whether a completion contains usable assistant output."""
        try:
            message = response.choices[0].message
        except (AttributeError, IndexError, TypeError):
            return False

        content = getattr(message, "content", None)
        raw_calls = getattr(message, "tool_calls", None)
        return bool(content and str(content).strip()) or bool(raw_calls)

    def _post_chat(self, **kwargs: Any):
        """POST /chat/completions with transient-failure backoff.

        Two retry dimensions:
        1. HTTP-level: 429/5xx with exponential backoff.
        2. Content-level: a successful response with neither usable text nor
           tool calls. Reasoning-style models can consume the output budget
           before emitting visible content; retrying here keeps that provider
           quirk from poisoning downstream parsing and review gates.

        Non-retryable failures raise immediately. After the content retry
        budget is exhausted, the final provider response is returned so the
        existing upper layer remains responsible for reporting malformed
        output.
        """
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

        response = self._post_chat(**kwargs)

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
