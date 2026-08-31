from __future__ import annotations

import json

from agents import developer as developer_module
from runtime.agent_config import AgentConfig
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall
from runtime.task import Task
from runtime.task_manager import TaskManager

from benchmarks.real_developer.executor import DeveloperAgentExecutor
from benchmarks.real_developer.fixture import isolated_benchmark_workspace


class _ReplayLLM(BaseLLM):
    """Deterministic tool-call script; ignores prompts so A/B receives identical replies."""

    def __init__(self) -> None:
        self._step = 0

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        return "done"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto") -> LLMResponse:
        self._step += 1
        if self._step <= 2:
            return LLMResponse(
                content=None,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"call-{self._step}",
                        name="read_file",
                        arguments=json.dumps({"path": "app/utils/helpers.py"}),
                    ),
                ),
                usage={"prompt_tokens": 10, "completion_tokens": 2},
            )
        return LLMResponse(content="done", usage={"prompt_tokens": 10, "completion_tokens": 2})


def _run(*, disable_cache: bool):
    task = Task(
        "TASK-CACHE-CONTROLLED-001",
        "Controlled cache comparison",
        "Read app/utils/helpers.py and finish after the fixed tool-call sequence.",
        "developer",
        status="ready",
    )
    manager = TaskManager([task])
    replay = _ReplayLLM()
    executor = DeveloperAgentExecutor(
        manager,
        1,
        llm_factory=lambda: replay,
        config_factory=lambda _: AgentConfig(),
    )

    if not disable_cache:
        return executor.run_task(task, "developer-1")

    original_cache = developer_module.ToolResultCache

    class _NoReadOnlyCache(original_cache):
        def contains(self, tool_name, arguments):
            if tool_name in getattr(developer_module, "CACHEABLE_TOOLS", ()):
                return False
            return super().contains(tool_name, arguments)

        def lookup(self, tool_name, arguments):
            if tool_name in getattr(developer_module, "CACHEABLE_TOOLS", ()):
                return None
            return super().lookup(tool_name, arguments)

    developer_module.ToolResultCache = _NoReadOnlyCache
    try:
        return executor.run_task(task, "developer-1")
    finally:
        developer_module.ToolResultCache = original_cache


def test_controlled_cache_comparison_is_causal_and_deterministic() -> None:
    with isolated_benchmark_workspace():
        baseline = _run(disable_cache=True)
        with isolated_benchmark_workspace():
            candidate = _run(disable_cache=False)

    assert baseline.failed is False
    assert candidate.failed is False
    assert baseline.tool_calls == candidate.tool_calls == 2
    assert baseline.duplicate_execution_tool_calls == 1
    assert candidate.duplicate_execution_tool_calls == 0
    assert baseline.cache_hits == 0
    assert candidate.cache_hits == 1
    assert baseline.input_tokens == candidate.input_tokens
