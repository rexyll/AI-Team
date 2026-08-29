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
from runtime.tool_loop_decision_budget import ToolLoopDecisionBudget
from security.prompt_injection import augment_system_prompt


class BaseAgent(ABC):
    def __init__(self, config: AgentConfig | None = None, *, llm: BaseLLM | None = None):
        self.config = config
        provider = llm if llm is not None else ProviderLLM()
        if not isinstance(provider, BaseLLM):
            raise TypeError(
                "BaseAgent llm must implement BaseLLM, "
                f"got {type(provider).__name__}"
            )
        self.llm = provider
        self.context_compactor = ContextCompactor()
        self.llm_metrics = LLMMetrics()
        self._tool_loop_decision_budget = ToolLoopDecisionBudget()
        self._tool_loop_budget_messages_id: int | None = None

    @property
    @abstractmethod
    def role(self) -> str:
        pass

    def build_context(self, task: Task, *, all_tasks: dict[str, Task] | None = None) -> AgentContext:
        return ContextBuilder(all_tasks=all_tasks).build_agent_context(task, role=self.role)

    def _generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        if isinstance(self.llm, ContextCompactingLLM):
            started = perf_counter()
            result = self.llm.generate(prompt, system_prompt=augment_system_prompt(system_prompt), temperature=temperature, max_tokens=max_tokens)
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compact_prompt, compact_system, stats = self.context_compactor.compact_prompt(prompt, system_prompt=augment_system_prompt(system_prompt))
            started = perf_counter()
            result = self.llm.generate(compact_prompt, system_prompt=compact_system, temperature=temperature, max_tokens=max_tokens)
            prompt_chars = stats.compacted_chars
            input_tokens = stats.compacted_tokens
        self.llm_metrics.record_llm_call(prompt_chars=prompt_chars, input_tokens=input_tokens, elapsed_seconds=perf_counter() - started)
        self.llm_metrics.finish()
        return result

    def _prepare_tool_loop_decision_budget(self, messages: list[dict[str, Any]]) -> None:
        """Record one decision turn and inject a soft reuse checkpoint when needed."""
        message_set_id = id(messages)
        if self._tool_loop_budget_messages_id != message_set_id:
            self._tool_loop_decision_budget = ToolLoopDecisionBudget()
            self._tool_loop_budget_messages_id = message_set_id
        state = self._tool_loop_decision_budget.record()
        if self._tool_loop_decision_budget.should_checkpoint():
            messages.append({
                "role": "user",
                "content": (
                    "DECISION BUDGET CHECKPOINT: "
                    f"{state.decisions} LLM decision turns have been used; "
                    f"soft limit={state.soft_limit}. Reuse established evidence "
                    "and the latest checkpoint before performing new exploration. "
                    "Do not repeat a read-only action whose evidence is already "
                    "available. Continue recovery or verification when correctness requires it."
                ),
            })

    def _generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        started = perf_counter()
        collapse_tool_loop_checkpoints(messages)
        self._prepare_tool_loop_decision_budget(messages)
        if isinstance(self.llm, ContextCompactingLLM):
            response = self.llm.generate_with_tools(messages, tools=tools, tool_choice=tool_choice, system_prompt=augment_system_prompt(""))
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compacted, stats = self.context_compactor.compact_messages(messages)
            response = self.llm.generate_with_tools(compacted, tools=tools, tool_choice=tool_choice, system_prompt=augment_system_prompt(""))
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
