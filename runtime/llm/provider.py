from __future__ import annotations

import os
import time
from typing import Any

from config.model import get_provider_profile
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall
from runtime.model_governance import ModelRoute, ModelUsage
from runtime.model_usage import ModelUsageLedger


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


class ProviderLLM(BaseLLM):
    """BaseLLM adapter for OpenAI-compatible provider clients.

    Provider and model selection is environment-driven. Tests and callers
    may inject a client directly; in that case no provider configuration is
    required because the client is already supplied by the caller.

    When ``project_id`` and a ``usage_ledger`` are supplied, every provider
    response is attributed to that project at this canonical invocation
    boundary. Attribution is telemetry only; admission and budget enforcement
    remain in ModelGovernance.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        provider_profile: str | None = None,
        client_instance: Any = None,
        project_id: str | None = None,
        usage_ledger: ModelUsageLedger | None = None,
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
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string")
        if usage_ledger is not None and not isinstance(usage_ledger, ModelUsageLedger):
            raise TypeError("usage_ledger must be a ModelUsageLedger")
        if project_id is None and usage_ledger is not None:
            raise ValueError("project_id is required when usage_ledger is supplied")

        self.provider_profile = resolved_profile
        self.model = resolved_model
        self.project_id = project_id.strip() if project_id is not None else None
        self.usage_ledger = usage_ledger
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

    def _attribute_usage(self, response: Any) -> None:
        if self.project_id is None or self.usage_ledger is None:
            return
        usage = self._usage_of(response)
        self.usage_ledger.record(
            self.project_id,
            ModelUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                llm_calls=1,
            ),
            route=ModelRoute(self.provider_profile, self.model),
        )

    @staticmethod
    def _message_diagnostic(message: Any) -> dict[str, Any]:
        if not isinstance(message, dict):
            return {"role": None, "content_chars": 0, "tool_call_ids": ()}
        raw_content = message.get("content")
        content_chars = len(str(raw_content)) if raw_content is not None else 0
        tool_calls = message.get("tool_calls") or ()
        tool_call_ids: list[str] = []
        tool_names: list[str] = []
        if isinstance(tool_calls, (list, tuple)):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                call_id = call.get("id")
                if isinstance(call_id, str):
                    tool_call_ids.append(call_id)
                function = call.get("function")
                if isinstance(function, dict) and isinstance(function.get("name"), str):
                    tool_names.append(function["name"])
        return {
            "role": message.get("role"),
            "content_chars": content_chars,
            "tool_call_ids": tuple(tool_call_ids),
            "tool_names": tuple(tool_names),
            "tool_call_id": message.get("tool_call_id"),
        }

    def _log_request_diagnostic(self, kwargs: dict[str, Any], exc: BaseException) -> None:
        if os.getenv("AGNES_REQUEST_DIAGNOSTICS", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        if self.provider_profile != "agnes":
            return
        messages = kwargs.get("messages")
        safe_messages = [self._message_diagnostic(message) for message in messages] if isinstance(messages, list) else []
        print(
            "[LLM DIAGNOSTIC] "
            f"provider={self.provider_profile} model={self.model} "
            f"message_count={len(safe_messages)} "
            f"roles={[item['role'] for item in safe_messages]} "
            f"last_messages={safe_messages[-5:]} "
            f"tools_count={len(kwargs.get('tools') or ())} "
            f"tool_choice={kwargs.get('tool_choice')} "
            f"error={type(exc).__name__}: {exc}"
        )

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
                        self._attribute_usage(response)
                        return response
                    wait = self._backoff_seconds(empty_attempt, None)
                    print(
                        f"[LLM] {self.provider_profile}/{self.model} "
                        f"empty response; retrying ({empty_attempt}/{max_attempts})"
                    )
                    time.sleep(wait)
                    continue

                self._attribute_usage(response)
                return response

            except Exception as exc:
                self._log_request_diagnostic(kwargs, exc)
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

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
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
