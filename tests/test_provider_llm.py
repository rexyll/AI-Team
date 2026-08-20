from types import SimpleNamespace

import pytest

from runtime.llm.base import BaseLLM
from runtime.llm.provider import ProviderLLM


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="provider response")
                )
            ]
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_provider_llm_implements_base_llm():
    assert isinstance(ProviderLLM(client_instance=FakeClient()), BaseLLM)


def test_provider_llm_maps_base_contract_to_openai_compatible_client():
    client = FakeClient()
    llm = ProviderLLM(model="test-model", client_instance=client)

    result = llm.generate(
        "user prompt",
        system_prompt="system prompt",
        temperature=0.7,
        max_tokens=123,
    )

    assert result == "provider response"
    assert client.chat.completions.calls == [
        {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
            "temperature": 0.7,
            "max_tokens": 123,
        }
    ]


def test_provider_llm_omits_empty_system_prompt():
    client = FakeClient()
    llm = ProviderLLM(client_instance=client)

    assert llm.generate("prompt") == "provider response"
    assert client.chat.completions.calls[0]["messages"] == [
        {"role": "user", "content": "prompt"}
    ]


def test_provider_llm_rejects_invalid_configuration():
    client = FakeClient()

    with pytest.raises(ValueError):
        ProviderLLM(model="", client_instance=client)

    with pytest.raises(TypeError):
        ProviderLLM(model=123, client_instance=client)  # type: ignore[arg-type]


def test_provider_llm_rejects_invalid_prompt_types():
    llm = ProviderLLM(client_instance=FakeClient())

    with pytest.raises(TypeError):
        llm.generate(123)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        llm.generate("prompt", system_prompt=123)  # type: ignore[arg-type]
