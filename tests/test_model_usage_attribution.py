from types import SimpleNamespace

import pytest

from runtime.llm.provider import ProviderLLM
from runtime.model_governance import ModelUsage
from runtime.model_usage import ModelUsageLedger


class _Completions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _Client:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=_Completions(response))


def _response(prompt_tokens=12, completion_tokens=7, content="ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def test_ledger_accumulates_usage_per_project_and_preserves_records():
    ledger = ModelUsageLedger()
    ledger.record("P1", ModelUsage(input_tokens=10, output_tokens=4, llm_calls=1))
    ledger.record("P2", ModelUsage(input_tokens=3, output_tokens=2, llm_calls=1))
    ledger.record("P1", ModelUsage(input_tokens=5, output_tokens=1, llm_calls=1))

    assert ledger.usage_for("P1") == ModelUsage(input_tokens=15, output_tokens=5, llm_calls=2)
    assert ledger.usage_for("P2") == ModelUsage(input_tokens=3, output_tokens=2, llm_calls=1)
    assert ledger.usage_for("missing") == ModelUsage()
    assert [record.project_id for record in ledger.records("P1")] == ["P1", "P1"]
    assert ledger.records("P1")[0].usage.llm_calls == 1


def test_provider_llm_attributes_actual_response_usage_to_project():
    ledger = ModelUsageLedger()
    client = _Client(_response(12, 7))
    llm = ProviderLLM(
        model="test-model",
        client_instance=client,
        project_id="P1",
        usage_ledger=ledger,
    )

    assert llm.generate("prompt") == "ok"
    assert ledger.usage_for("P1") == ModelUsage(input_tokens=12, output_tokens=7, llm_calls=1)


def test_tool_call_invocation_is_attributed_once():
    ledger = ModelUsageLedger()
    response = _response(20, 9)
    response.choices[0].message.tool_calls = [
        SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="read_file", arguments='{"path":"x.py"}'),
        )
    ]
    llm = ProviderLLM(
        model="test-model",
        client_instance=_Client(response),
        project_id="P1",
        usage_ledger=ledger,
    )

    result = llm.generate_with_tools([{"role": "user", "content": "inspect"}])

    assert len(result.tool_calls) == 1
    assert ledger.usage_for("P1") == ModelUsage(input_tokens=20, output_tokens=9, llm_calls=1)


def test_usage_ledger_requires_project_when_attached():
    with pytest.raises(ValueError, match="project_id is required"):
        ProviderLLM(model="test-model", client_instance=_Client(_response()), usage_ledger=ModelUsageLedger())


def test_provider_without_usage_ledger_keeps_existing_behavior():
    client = _Client(_response())
    llm = ProviderLLM(model="test-model", client_instance=client)

    assert llm.generate("prompt") == "ok"
