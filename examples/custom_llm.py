from runtime.llm.base import BaseLLM


class ExampleLLM(BaseLLM):
    """Minimal provider-independent LLM implementation for local examples."""

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        return (
            f"example-response: {prompt[:80]}"
            f" | temperature={temperature} | max_tokens={max_tokens}"
        )


def build_example_llm() -> BaseLLM:
    return ExampleLLM()


if __name__ == "__main__":
    llm = build_example_llm()
    print(llm.generate("Explain the canonical AgentResult contract."))
