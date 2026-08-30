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
from runtime.llm_metrics import LLMMetrics
from runtime.llm.provider import ProviderLLM
from runtime.task import Task
from runtime.tool_loop_checkpoint import collapse_tool_loop_checkpoints
from runtime.tool_loop_decision_budget import ToolLoopDecisionBudget
from security.prompt_injection import augment_system_prompt, untrusted_content
from security.runtime_capability import DEFAULT_RUNTIME_CAPABILITY_POLICY


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

    def _secured_system_prompt(self, system_prompt: str) -> str:
        """Compile the agent instructions with the common trust-boundary policy."""
        return augment_system_prompt(system_prompt)

    def _generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        secured_system_prompt = self._secured_system_prompt(system_prompt)
        if isinstance(self.llm, ContextCompactingLLM):
            started = perf_counter()
            result = self.llm.generate(prompt, system_prompt=secured_system_prompt, temperature=temperature, max_tokens=max_tokens)
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compact_prompt, compact_system, stats = self.context_compactor.compact_prompt(prompt, system_prompt=secured_system_prompt)
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

    def _authorized_tool_schemas(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Expose only tools authorized for this agent role to the model."""
        if tools is None:
            return None
        authorized = []
        for schema in tools:
            function = schema.get("function", {}) if isinstance(schema, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(name, str) and DEFAULT_RUNTIME_CAPABILITY_POLICY.allows(self.role, name):
                authorized.append(schema)
        return authorized

    @staticmethod
    def _secure_tool_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fence tool-produced content before it is sent back to the model.

        Tool output is data supplied by the execution environment and may
        contain repository text, command output, generated files, or hostile
        instructions.  The original message list is left untouched so runtime
        history and audit data preserve the actual tool result.
        """
        secured: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "tool":
                secured.append(message)
                continue
            copied = dict(message)
            copied["content"] = untrusted_content(
                f"tool.result.{message.get('tool_call_id', 'unknown')}",
                message.get("content", ""),
            )
            secured.append(copied)
        return secured

    def _generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        started = perf_counter()
        collapse_tool_loop_checkpoints(messages)
        self._prepare_tool_loop_decision_budget(messages)
        security_prompt = self._secured_system_prompt("")
        secured_messages = ([{"role": "system", "content": security_prompt}] if security_prompt else []) + self._secure_tool_messages(messages)
        authorized_tools = self._authorized_tool_schemas(tools)
        if isinstance(self.llm, ContextCompactingLLM):
            response = self.llm.generate_with_tools(secured_messages, tools=authorized_tools, tool_choice=tool_choice)
            prompt_chars = self.llm.last_prompt_chars_after
            input_tokens = self.llm.last_input_tokens_after
        else:
            compacted, stats = self.context_compactor.compact_messages(secured_messages)
            response = self.llm.generate_with_tools(compacted, tools=authorized_tools, tool_choice=tool_choice)
            prompt_chars = stats.compacted_chars
            input_tokens = stats.compacted_tokens
        for tool_call in response.tool_calls:
            DEFAULT_RUNTIME_CAPABILITY_POLICY.require(self.role, tool_call.name)
        self.llm_metrics.record_llm_call(prompt_chars=prompt_chars, input_tokens=input_tokens, elapsed_seconds=perf_counter() - started)
        self.llm_metrics.record_tool_calls(len(response.tool_calls))
        self.llm_metrics.finish()
        return response

    def metrics_snapshot(self):
        return self.llm_metrics.snapshot()

    @abstractmethod
    def run(self, task: Task) -> AgentResult:
        pass
