"""Transient-failure backoff contracts for ProviderLLM.

Upstream shared pools (e.g. OpenRouter stealth models) return transient
429s. A single rate-limit hit used to kill a whole developer task mid-
project; now the provider adapter retries 429/5xx with exponential
backoff (honoring numeric Retry-After) and only then fails.
"""

from __future__ import annotations

import pytest

import runtime.llm.provider as provider_module
from runtime.llm.provider import ProviderLLM


class _RateLimit(Exception):
    def __init__(self, code: int = 429, headers: dict | None = None) -> None:
        self.status_code = code
        self.response = type("R", (), {"headers": headers or {}})()
        super().__init__(f"Error code: {code}")


class _BadRequest(Exception):
    status_code = 400

    def __init__(self) -> None:
        super().__init__("Error code: 400 - bad request")


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls = None


class _FakeCompletions:
    def __init__(self, script: list) -> None:
        # script items: ("ok", content) or ("raise", exception)
        self._script = list(script)
        self.calls = 0
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        if not self._script:
            return self._response("ok")
        kind, payload = self._script.pop(0)
        if kind == "raise":
            raise payload
        return self._response(payload)

    @staticmethod
    def _response(content: str):
        message = type("M", (), {"content": content, "tool_calls": None})
        choice = type("C", (), {"message": message()})
        return type("R", (), {"choices": [choice()]})()


class _FakeClient:
    """Shape expected by ProviderLLM: ``client.chat.completions.create``."""

    def __init__(self, completions: "_FakeCompletions") -> None:
        self.chat = type("Chat", (), {"completions": completions})


def _llm_with(script: list) -> tuple[ProviderLLM, _FakeCompletions]:
    completions = _FakeCompletions(script)
    llm = ProviderLLM(client_instance=_FakeClient(completions))
    return llm, completions


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


def test_transient_429_retries_then_succeeds(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)

    llm, fake = _llm_with(
        [("raise", _RateLimit(429)), ("raise", _RateLimit(429)), ("ok", "done")]
    )

    assert llm.generate("hi") == "done"
    assert fake.calls == 3          # 两次失败 + 第三次成功
    assert sleeps == [2.0, 4.0]     # 指数退避：2s → 4s


def test_non_retryable_fails_immediately(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)

    llm, fake = _llm_with([("raise", _BadRequest())])

    with pytest.raises(_BadRequest):
        llm.generate("hi")

    assert fake.calls == 1
    assert sleeps == []


def test_retry_budget_exhaustion_raises(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)

    script = [("raise", _RateLimit(429))] * 5
    llm, fake = _llm_with(script)

    with pytest.raises(_RateLimit):
        llm.generate("hi")

    assert fake.calls == 2          # 只重试到预算上限
    assert len(sleeps) == 1         # 仅一次退避间隔


def test_retry_after_header_is_honored(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)

    llm, fake = _llm_with(
        [("raise", _RateLimit(429, headers={"retry-after": "7"})), ("ok", "done")]
    )

    assert llm.generate("hi") == "done"
    assert sleeps == [7.0]


# ---------------------------------------------------------------------------
# generate_with_tools() shares the same retry boundary
# ---------------------------------------------------------------------------


def test_generate_with_tools_retries_transient_failures(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)

    llm, fake = _llm_with([("raise", _RateLimit(503)), ("ok", "final answer")])

    response = llm.generate_with_tools([{"role": "user", "content": "go"}])

    assert response.content == "final answer"
    assert fake.calls == 2
    assert sleeps == [2.0]
