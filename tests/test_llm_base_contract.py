import inspect

import pytest

from runtime.llm.base import BaseLLM


class StubLLM(BaseLLM):
    def __init__(self):
        self.calls = []

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return "stub response"


def test_base_llm_is_abstract():
    assert inspect.isabstract(BaseLLM)
    with pytest.raises(TypeError):
        BaseLLM()


def test_base_llm_exposes_stable_generate_contract():
    signature = inspect.signature(BaseLLM.generate)
    parameters = list(signature.parameters.values())

    assert [parameter.name for parameter in parameters] == [
        "self",
        "prompt",
        "system_prompt",
        "temperature",
        "max_tokens",
    ]
    assert parameters[1].annotation is str
    assert parameters[2].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[3].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[4].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[2].default == ""
    assert parameters[3].default == 0.2
    assert parameters[4].default == 4096
    assert signature.return_annotation is str


def test_base_llm_contract_supports_prompt_and_generation_options():
    llm = StubLLM()

    result = llm.generate(
        "user prompt",
        system_prompt="system prompt",
        temperature=0.7,
        max_tokens=123,
    )

    assert result == "stub response"
    assert llm.calls == [
        {
            "prompt": "user prompt",
            "system_prompt": "system prompt",
            "temperature": 0.7,
            "max_tokens": 123,
        }
    ]


def test_base_llm_contract_allows_default_generation_options():
    llm = StubLLM()

    assert llm.generate("user prompt") == "stub response"
    assert llm.calls == [
        {
            "prompt": "user prompt",
            "system_prompt": "",
            "temperature": 0.2,
            "max_tokens": 4096,
        }
    ]
