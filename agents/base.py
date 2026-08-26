from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from runtime.agent_config import AgentConfig
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_builder import ContextBuilder
from runtime.context_compaction import ContextCompactor
from runtime.llm.base import BaseLLM, LLMResponse
from runtime.llm.context_compacting import ContextCompactingLLM
from runtime.llm.provider import ProviderLLM
from runtime.llm_metrics import LLMMetrics
from runtime.task import Task


class BaseAgent(ABC):

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        llm: BaseLLM | None = None,
    ):
        self.config = config
        provider = llm if llm is not None else ProviderLLM()
        if not isinstance(provider, BaseLLM):
            raise TypeError(
                "BaseAgent llm must implement BaseLLM, "
                f"got {type(provider).__name__}"
            )

        # DeveloperAgent has an existing runtime contract around
        # ContextCompactingLLM (the real-developer benchmark inspects its
        # compaction events). Keep that decorator as the single context
        # boundary for tool loops; it now delegates to the same ContextCompactor
        # used by BaseAgent's ordinary LLM calls.
        if self.role == "developer" and not isinstance(provider, ContextCompactingLLM):
            provider = ContextCompactingLLM(provider)

        self.llm = provider
        self.context_compactor = ContextCompactor()
        self.llm_metrics = LLMMetrics()

    @property
    @abstractmethod
    def role(self) -> str:
        pass

    def build_context(
        self,
        task: Task,
        *,
        all_tasks: dict[str, Task] | None = None,
    ) -> AgentContext:
        """Build the canonical AgentContext used by this Agent."""
        return ContextBuilder(
            all_tasks=all_tasks,
        ).build_agent_context(
            task,
            role=self.role,
        )

    def _generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Generate through the shared bounded-context LLM boundary."""
        compact_prompt, compact_system, stats = self.context_compactor.compact_prompt(
            prompt,
            system_prompt=system_prompt,
        )
        started = perf_counter()
        result = self.llm.generate(
            compact_prompt,
            system_prompt=compact_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.llm_metrics.record_llm_call(
            prompt_chars=stats.compacted_chars,
            input_tokens=stats.compacted_tokens,
            elapsed_seconds=perf_counter() - started,
        )
        self.llm_metrics.finish()
        return result

    def _generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Generate with tools through exactly one context-compaction boundary."""
        started = perf_counter()
        if isinstance(self.llm, ContextCompactingLLM):
            # ContextCompactingLLM owns the actual payload compaction. Reading
            # its last stats keeps BaseAgent telemetry aligned with the exact
            # request that reaches the wrapped provider.
            response = self.llm.generate_with_tools(
                messages,
                tools=tools,
                tool_choice=tool_choice,
            )
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compacted, stats = self.context_compactor.compact_messages(messages)
            response = self.llm.generate_with_tools(
                compacted,
                tools=tools,
                tool_choice=tool_choice,
            )
            prompt_chars = stats.compacted_chars
            input_tokens = stats.compacted_tokens

        self.llm_metrics.record_llm_call(
            prompt_chars=prompt_chars,
            input_tokens=input_tokens,
            elapsed_seconds=perf_counter() - started,
        )
        self.llm_metrics.record_tool_calls(len(response.tool_calls))
        self.llm_metrics.finish()
        return response

    def metrics_snapshot(self):
        """Return a stable snapshot of current LLM/context metrics."""
        return self.llm_metrics.snapshot()

    @abstractmethod
    def run(self, task: Task) -> AgentResult:
        """Execute one AI Team task."""
        pass
