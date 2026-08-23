from abc import ABC, abstractmethod
from dataclasses import dataclass
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
    """Provider-neutral completion result.

    ``content`` carries assistant text; ``tool_calls`` lists requested tool
    invocations. A turn typically produces one of the two, mirroring
    tool-calling chat semantics across providers and mocks.
    """

    content: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()


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
        """Tool-calling boundary used by agent execution loops.

        The default implementation degrades gracefully to text-only
        completion: the last user message is routed through
        :meth:`generate` and no tool calls are returned. Provider-backed
        implementations override this with native tool calling;
        deterministic mocks may script tool-call turns. Subclasses that
        only implement :meth:`generate` therefore stay compatible with
        every agent without any code change.
        """
        prompt = ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    prompt = content
                    break

        return LLMResponse(content=self.generate(prompt))
