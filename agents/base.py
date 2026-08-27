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
from runtime.tool_loop_checkpoint import collapse_tool_loop_checkpoints


class BaseAgent(ABC):
    def __init__(self, config: AgentConfig | None = None, *, llm: BaseLLM | None = None):
        self.config = config
        provider = llm if llm is not None else ProviderLLM()
        if not isinstance(provider, BaseLLM):
            raise TypeError(
                "BaseAgent llm must implement BaseLLM, "
                f"got {type(provider).__name__}"
            )
        # Keep dependency injection transparent. The owning runtime boundary
        # may explicitly install ContextCompactingLLM; otherwise BaseAgent
        # applies the shared compactor directly without changing llm identity.
        self.llm = provider
        self.context_compactor = ContextCompactor()
        self.llm_metrics = LLMMetrics()

    @property
    @abstractmethod
    def role(self) -> str:
        pass

    def build_context(self, task: Task, *, all_tasks: dict[str, Task] | None = None) -> AgentContext:
        return ContextBuilder(all_tasks=all_tasks).build_agent_context(task, role=self.role)

    def _generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        if isinstance(self.llm, ContextCompactingLLM):
            started = perf_counter()
            result = self.llm.generate(prompt, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens)
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compact_prompt, compact_system, stats = self.context_compactor.compact_prompt(prompt, system_prompt=system_prompt)
            started = perf_counter()
            result = self.llm.generate(compact_prompt, system_prompt=compact_system, temperature=temperature, max_tokens=max_tokens)
            prompt_chars = stats.compacted_chars
            input_tokens = stats.compacted_tokens
        self.llm_metrics.record_llm_call(prompt_chars=prompt_chars, input_tokens=input_tokens, elapsed_seconds=perf_counter() - started)
        self.llm_metrics.finish()
        return result

    def _generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        started = perf_counter()
        collapse_tool_loop_checkpoints(messages)
        if isinstance(self.llm, ContextCompactingLLM):
            response = self.llm.generate_with_tools(messages, tools=tools, tool_choice=tool_choice)
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compacted, stats = self.context_compactor.compact_messages(messages)
            response = self.llm.generate_with_tools(compacted, tools=tools, tool_choice=tool_choice)
            prompt_chars = stats.compacted_chars
            input_tokens = stats.compacted_tokens
        self.llm_metrics.record_llm_call(prompt_chars=prompt_chars, input_tokens=input_tokens, elapsed_seconds=perf_counter() - started)
        self.llm_metrics.record_tool_calls(len(response.tool_calls))
        self.llm_metrics.finish()
        return response

    def metrics_snapshot(self):
        return self.llm_metrics.snapshot()

    @abstractmethod
    def run(self, task: Task) -> AgentResult:
        pass
