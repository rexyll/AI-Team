from abc import ABC, abstractmethod
from typing import Any
from time import perf_counter

from runtime.agent_config import AgentConfig
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_builder import ContextBuilder
from runtime.context_compaction import ContextCompactor
from runtime.llm.base import BaseLLM, LLMResponse
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
        self.llm = llm if llm is not None else ProviderLLM()

        if not isinstance(self.llm, BaseLLM):
            raise TypeError(
                "BaseAgent llm must implement BaseLLM, "
                f"got {type(self.llm).__name__}"
            )

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
        """
        Build the canonical AgentContext used by this Agent.

        This is the compatibility bridge for the Phase 3 AgentContext
        migration. Existing workflow code can continue passing Task to
        ``run()``, while Agents that have migrated to AgentContext can use
        this helper to obtain an isolated execution snapshot.
        """
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
        """Generate with tools after compacting conversation history."""
        compacted, stats = self.context_compactor.compact_messages(messages)
        started = perf_counter()
        response = self.llm.generate_with_tools(
            compacted,
            tools=tools,
            tool_choice=tool_choice,
        )
        self.llm_metrics.record_llm_call(
            prompt_chars=stats.compacted_chars,
            input_tokens=stats.compacted_tokens,
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
        """
        Execute one AI Team task.

        All agents must receive a runtime.task.Task object and return an
        AgentResult. During Phase 3, individual Agents will progressively
        migrate their internal execution logic to AgentContext.
        """
        pass
