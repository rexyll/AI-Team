import pytest

from runtime.llm.base import BaseLLM
from runtime.llm.mock import MockLLM


def test_mock_llm_implements_base_llm():
    assert isinstance(MockLLM(), BaseLLM)


def test_mock_llm_returns_deterministic_default_response():
    llm = MockLLM()

    assert llm.generate("first") == "MOCK_RESPONSE"
    assert llm.generate("second") == "MOCK_RESPONSE"


def test_mock_llm_returns_configured_fallback_response():
    llm = MockLLM(response="fixed response")

    assert llm.generate("prompt") == "fixed response"


def test_mock_llm_consumes_response_queue_in_fifo_order():
    llm = MockLLM(response="fallback", responses=["one", "two"])

    assert llm.remaining_responses == 2
    assert llm.generate("prompt-1") == "one"
    assert llm.generate("prompt-2") == "two"
    assert llm.remaining_responses == 0
    assert llm.generate("prompt-3") == "fallback"


def test_mock_llm_records_generation_arguments():
    llm = MockLLM()

    llm.generate(
        "user prompt",
        system_prompt="system prompt",
        temperature=0.7,
        max_tokens=123,
    )

    assert llm.calls == [
        {
            "prompt": "user prompt",
            "system_prompt": "system prompt",
            "temperature": 0.7,
            "max_tokens": 123,
        }
    ]


def test_mock_llm_records_independent_call_snapshots():
    llm = MockLLM()
    prompt = "original"

    llm.generate(prompt)
    prompt = "changed"

    assert llm.calls[0]["prompt"] == "original"


def test_mock_llm_reset_clears_calls_but_preserves_queue():
    llm = MockLLM(responses=["queued"])
    llm.generate("prompt")
    llm.reset()

    assert llm.calls == []
    assert llm.remaining_responses == 0


def test_mock_llm_rejects_invalid_response_configuration():
    with pytest.raises(TypeError):
        MockLLM(response=123)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        MockLLM(responses=["ok", 123])  # type: ignore[list-item]


def test_mock_llm_rejects_invalid_generate_arguments():
    llm = MockLLM()

    with pytest.raises(TypeError):
        llm.generate(123)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        llm.generate("prompt", system_prompt=123)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        llm.generate("prompt", temperature="hot")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        llm.generate("prompt", max_tokens=1.5)  # type: ignore[arg-type]
