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

    with pytest.raises(TypeError):
        ProviderLLM(model=123, client_instance=client)  # type: ignore[arg-type]


def test_provider_llm_rejects_invalid_prompt_types():
    llm = ProviderLLM(client_instance=FakeClient())

    with pytest.raises(TypeError):
        llm.generate(123)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        llm.generate("prompt", system_prompt=123)  # type: ignore[arg-type]


def test_agnes_tool_continuation_preserves_standard_message_shape():
    client = FakeClient()
    llm = ProviderLLM(model="agnes-2.5-flash", provider_profile="agnes", client_instance=client)

    llm.generate_with_tools(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Complete the task."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{\"path\": \"x.py\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "content"},
        ]
    )

    messages = client.chat.completions.calls[0]["messages"]
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "content",
    }
    assert messages.count({"role": "user", "content": "Complete the task."}) == 1


def test_non_agnes_provider_preserves_standard_tool_continuation_shape(monkeypatch):
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://example.invalid/v1")
    client = FakeClient()
    llm = ProviderLLM(model="test-model", provider_profile="custom", client_instance=client)

    llm.generate_with_tools(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Complete the task."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{\"path\": \"x.py\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "content"},
        ]
    )

    messages = client.chat.completions.calls[0]["messages"]
    assert messages[-1] == {"role": "tool", "tool_call_id": "call-1", "content": "content"}


def test_agnes_request_diagnostics_are_disabled_by_default(capsys):
    llm = ProviderLLM(model="agnes-2.5-flash", provider_profile="agnes", client_instance=FakeClient())
    llm._log_request_diagnostic(
        {"model": llm.model, "messages": [{"role": "user", "content": "secret"}]},
        RuntimeError("boom"),
    )
    assert capsys.readouterr().out == ""


def test_agnes_request_diagnostics_redact_message_content(monkeypatch, capsys):
    monkeypatch.setenv("AGNES_REQUEST_DIAGNOSTICS", "1")
    llm = ProviderLLM(model="agnes-2.5-flash", provider_profile="agnes", client_instance=FakeClient())
    llm._log_request_diagnostic(
        {
            "model": llm.model,
            "messages": [
                {"role": "system", "content": "secret-system"},
                {"role": "user", "content": "secret-user"},
                {"role": "tool", "tool_call_id": "call-1", "content": "secret-tool-result"},
            ],
            "tools": [{"function": {"name": "read_file"}}],
            "tool_choice": "auto",
        },
        RuntimeError("boom"),
    )
    output = capsys.readouterr().out
    assert "provider=agnes" in output
    assert "model=agnes-2.5-flash" in output
    assert "roles=['system', 'user', 'tool']" in output
    assert "secret-system" not in output
    assert "secret-user" not in output
    assert "secret-tool-result" not in output
    assert "tools_count=1" in output
    assert "tool_choice=auto" in output
