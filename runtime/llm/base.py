from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMToolCall:
    """Provider-neutral description of one model-requested tool invocation."""

    call_id: str
    name: str
    # Raw JSON-encoded arguments string, mirroring the provider wire format.
    arguments: str


@dataclass(frozen=True)
class LLMResponse:
    """Provider-neutral completion result plus optional usage telemetry."""

    content: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    latency_seconds: float | None = None


class BaseLLM(ABC):

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        pass

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Tool-calling boundary used by agent execution loops."""
        prompt = ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    prompt = content
                    break

        return LLMResponse(content=self.generate(prompt))
