from types import SimpleNamespace

from runtime.llm.provider import ProviderLLM


class _FakeCompletions:
    def create(self, **kwargs):
        message = SimpleNamespace(content="ok", tool_calls=[])
        usage = SimpleNamespace(prompt_tokens=12, completion_tokens=7, total_tokens=19)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=usage,
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_provider_llm_exposes_usage_and_latency():
    llm = ProviderLLM(
        model="test-model",
        client_instance=_FakeClient(),
    )

    response = llm.generate_with_tools(
        [{"role": "user", "content": "hello"}],
    )

    assert response.content == "ok"
    assert response.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }
    assert response.latency_seconds is not None
    assert response.latency_seconds >= 0
