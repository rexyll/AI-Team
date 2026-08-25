from __future__ import annotations

from types import SimpleNamespace

from runtime.llm.provider import ProviderLLM


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def _response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_empty_content_is_retried_until_non_empty(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_BACKOFF_SECONDS", "0")
    sleeps = []
    monkeypatch.setattr("runtime.llm.provider.time.sleep", sleeps.append)

    client = _FakeClient(
        [
            _response(""),
            _response(None),
            _response("APPROVED\nLooks good."),
        ]
    )
    llm = ProviderLLM(model="test-model", client_instance=client)

    result = llm.generate("review this")

    assert result == "APPROVED\nLooks good."
    assert client.chat.completions.calls == 3
    assert len(sleeps) == 2


def test_empty_content_returns_last_response_after_retry_budget(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_BACKOFF_SECONDS", "0")
    monkeypatch.setattr("runtime.llm.provider.time.sleep", lambda _: None)

    client = _FakeClient([_response(""), _response(" ")])
    llm = ProviderLLM(model="test-model", client_instance=client)

    assert llm.generate("review this") == ""
    assert client.chat.completions.calls == 2


def test_whitespace_only_content_is_normalized_after_retry_budget(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_BACKOFF_SECONDS", "0")
    monkeypatch.setattr("runtime.llm.provider.time.sleep", lambda _: None)

    client = _FakeClient([_response("\n\t"), _response("   ")])
    llm = ProviderLLM(model="test-model", client_instance=client)

    assert llm.generate("review this") == ""
    assert client.chat.completions.calls == 2


def test_meaningful_content_preserves_leading_and_trailing_whitespace():
    client = _FakeClient([_response("  APPROVED  ")])
    llm = ProviderLLM(model="test-model", client_instance=client)

    assert llm.generate("review this") == "  APPROVED  "
    assert client.chat.completions.calls == 1


def test_tool_call_response_is_not_treated_as_empty(monkeypatch):
    monkeypatch.setenv("LLM_BACKOFF_SECONDS", "0")
    sleeps = []
    monkeypatch.setattr("runtime.llm.provider.time.sleep", sleeps.append)

    tool_call = [SimpleNamespace(id="call-1", function=SimpleNamespace(name="x", arguments="{}"))]
    client = _FakeClient([_response(None, tool_call)])
    llm = ProviderLLM(model="test-model", client_instance=client)

    response = llm.generate_with_tools(
        [{"role": "user", "content": "do it"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
    )

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "x"
    assert client.chat.completions.calls == 1
    assert sleeps == []
