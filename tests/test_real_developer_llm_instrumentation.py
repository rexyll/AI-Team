from benchmarks.real_developer.llm_instrumentation import InstrumentedLLM
from runtime.llm.base import BaseLLM, LLMResponse


class _FakeLLM(BaseLLM):
    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return "ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        return LLMResponse(
            content="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        )


def test_instrumented_llm_counts_text_completion():
    llm = InstrumentedLLM(_FakeLLM())
    assert llm.generate("hello") == "ok"
    assert llm.stats.calls == 1
    assert llm.stats.input_tokens == 0
    assert llm.stats.output_tokens == 0
    assert llm.stats.latency_seconds >= 0


def test_instrumented_llm_collects_tool_call_usage():
    llm = InstrumentedLLM(_FakeLLM())
    response = llm.generate_with_tools([{"role": "user", "content": "hello"}])
    assert response.content == "ok"
    assert llm.stats.calls == 1
    assert llm.stats.input_tokens == 10
    assert llm.stats.output_tokens == 4
    assert llm.stats.total_tokens == 14
