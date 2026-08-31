from abc import ABC, abstractmethod
from functools import wraps
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
from runtime.tracing import DEFAULT_TRACER
from security.prompt_injection import augment_system_prompt, fence_developer_prompt, untrusted_content
from security.runtime_capability import DEFAULT_RUNTIME_CAPABILITY_POLICY


class BaseAgent(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        run = cls.__dict__.get("run")
        if run is None or getattr(run, "_ai_team_traced", False):
            return

        @wraps(run)
        def traced_run(self, task: Task):
            # Validate the public runtime contract before tracing touches task attributes. Invalid callers must receive the documented TypeError, not an incidental AttributeError from task.id below.
            if not isinstance(task, Task):
                raise TypeError(f"{self.__class__.__name__}.run() expects Task, got {type(task).__name__}")
            with DEFAULT_TRACER.span(f"workflow.stage.{self.role}", attributes={"task_id": task.id, "agent_role": self.role, "stage": self.role}) as span:
                result = run(self, task)
                if isinstance(result, AgentResult):
                    span.set_attribute("result.status", result.status)
                return result

        traced_run._ai_team_traced = True
        cls.run = traced_run

    def __init__(self, config: AgentConfig | None = None, *, llm: BaseLLM | None = None):
        self.config = config
        provider = llm if llm is not None else ProviderLLM()
        if not isinstance(provider, BaseLLM):
            raise TypeError("BaseAgent llm must implement BaseLLM, " f"got {type(provider).__name__}")
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
        return augment_system_prompt(system_prompt)

    def _generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        secured_system_prompt = self._secured_system_prompt(system_prompt)
        with DEFAULT_TRACER.span("llm.generate", attributes={"agent_role": self.role, "operation": "generate"}) as span:
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
            span.set_attribute("prompt_chars", prompt_chars)
            span.set_attribute("input_tokens", input_tokens)
        self.llm_metrics.record_llm_call(prompt_chars=prompt_chars, input_tokens=input_tokens, elapsed_seconds=perf_counter() - started)
        self.llm_metrics.finish()
        return result

    def _prepare_tool_loop_decision_budget(self, messages: list[dict[str, Any]]) -> None:
        message_set_id = id(messages)
        if self._tool_loop_budget_messages_id != message_set_id:
            self._tool_loop_decision_budget = ToolLoopDecisionBudget()
            self._tool_loop_budget_messages_id = message_set_id
        state = self._tool_loop_decision_budget.record()
        if self._tool_loop_decision_budget.should_checkpoint():
            messages.append({"role": "user", "content": ("DECISION BUDGET CHECKPOINT: " f"{state.decisions} LLM decision turns have been used; " f"soft limit={state.soft_limit}. Reuse established evidence and the latest checkpoint before performing new exploration. " "Do not repeat a read-only action whose evidence is already available. Continue recovery or verification when correctness requires it.")})

    def _authorized_tool_schemas(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
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
        secured: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "tool":
                secured.append(message)
                continue
            copied = dict(message)
            copied["content"] = untrusted_content(f"tool.result.{message.get('tool_call_id', 'unknown')}", message.get("content", ""))
            secured.append(copied)
        return secured

    def _secure_model_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        secured = self._secure_tool_messages(messages)
        if self.role != "developer":
            return secured
        fenced: list[dict[str, Any]] = []
        initial_user_seen = False
        for message in secured:
            if isinstance(message, dict) and message.get("role") == "user":
                copied = dict(message)
                content = copied.get("content", "")
                if isinstance(content, str):
                    if not initial_user_seen:
                        copied["content"] = fence_developer_prompt(content)
                        initial_user_seen = True
                    elif content.startswith("TOOL LOOP CHECKPOINT") or content.startswith("DECISION BUDGET CHECKPOINT"):
                        copied["content"] = untrusted_content("tool_loop.checkpoint", content)
                fenced.append(copied)
            else:
                fenced.append(message)
        return fenced

    def _generate_with_tools(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> LLMResponse:
        started = perf_counter()
        collapse_tool_loop_checkpoints(messages)
        self._prepare_tool_loop_decision_budget(messages)
        security_prompt = self._secured_system_prompt("")
        secured_messages = self._secure_model_messages(messages)
        if secured_messages and secured_messages[0].get("role") == "system":
            secured_messages[0] = {"role": "system", "content": security_prompt}
        elif security_prompt:
            secured_messages.insert(0, {"role": "system", "content": security_prompt})
        authorized_tools = self._authorized_tool_schemas(tools)
        with DEFAULT_TRACER.span("llm.generate_with_tools", attributes={"agent_role": self.role, "operation": "generate_with_tools"}) as span:
            if isinstance(self.llm, ContextCompactingLLM):
                response = self.llm.generate_with_tools(secured_messages, tools=authorized_tools, tool_choice=tool_choice)
                prompt_chars = self.llm.last_prompt_chars_after
                input_tokens = self.llm.last_input_tokens_after
            else:
                compacted, stats = self.context_compactor.compact_messages(secured_messages)
                response = self.llm.generate_with_tools(compacted, tools=authorized_tools, tool_choice=tool_choice)
                prompt_chars = stats.compacted_chars
                input_tokens = stats.compacted_tokens
            span.set_attribute("prompt_chars", prompt_chars)
            span.set_attribute("input_tokens", input_tokens)
            span.set_attribute("tool_call_count", len(response.tool_calls))
        for tool_call in response.tool_calls:
            DEFAULT_RUNTIME_CAPABILITY_POLICY.require(self.role, tool_call.name)
        self.llm_metrics.record_llm_call(prompt_chars=prompt_chars, input_tokens=input_tokens, elapsed_seconds=perf_counter() - started)
        self.llm_metrics.record_tool_calls(len(response.tool_calls))
        self.llm_metrics.finish()
        return response

    def metrics_snapshot(self):
        return self.llm_metrics.snapshot()

    @abstractmethod
    def run(self, task: Task):
        pass
