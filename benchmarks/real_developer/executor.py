from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from agents.developer import DeveloperAgent
from runtime.agent_config import AgentConfig
from runtime.llm.base import BaseLLM
from runtime.llm.context_compacting import ContextCompactingLLM
from runtime.task import Task
from runtime.task_manager import TaskManager

from .llm_instrumentation import InstrumentedLLM
from .metrics import RealDeveloperTaskMetrics


@dataclass
class _DeveloperBinding:
    developer_id: str
    agent: DeveloperAgent
    llm: InstrumentedLLM


class DeveloperAgentExecutor:
    """Execute real DeveloperAgent instances with per-developer telemetry."""

    def __init__(
        self,
        manager: TaskManager,
        developer_count: int,
        *,
        llm_factory: Callable[[], BaseLLM],
        config_factory: Callable[[int], AgentConfig | None] | None = None,
    ) -> None:
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")
        self.manager = manager
        self.developer_count = developer_count
        self._bindings: list[_DeveloperBinding] = []
        for index in range(developer_count):
            llm = InstrumentedLLM(llm_factory())
            config = config_factory(index + 1) if config_factory else None
            compacting_llm = ContextCompactingLLM(llm)
            self._bindings.append(
                _DeveloperBinding(
                    developer_id=f"developer-{index + 1}",
                    agent=DeveloperAgent(config=config, llm=compacting_llm),
                    llm=llm,
                )
            )

    def run_task(self, task: Task, developer_id: str) -> RealDeveloperTaskMetrics:
        binding = next((item for item in self._bindings if item.developer_id == developer_id), None)
        if binding is None:
            raise ValueError(f"unknown developer_id: {developer_id}")

        before_calls = binding.llm.stats.calls
        before_input = binding.llm.stats.input_tokens
        before_output = binding.llm.stats.output_tokens
        before_latency = binding.llm.stats.latency_seconds
        before_profiles = len(binding.llm.stats.profiles)
        compacting_llm = binding.agent.llm
        if not isinstance(compacting_llm, ContextCompactingLLM):
            raise TypeError("DeveloperAgent must use ContextCompactingLLM")
        before_events = len(compacting_llm.compaction_events)

        started = perf_counter()
        tool_calls = 0
        test_commands = 0
        self.manager.mark_running(task.id)
        try:
            result = binding.agent.run(task)
            validation = result.data.get("validation", {}) if isinstance(result.data, dict) else {}
            tool_calls = int(validation.get("tool_call_count", 0) or 0)
            test_commands = int(validation.get("test_command_count", 0) or 0)
            if result.status == "completed":
                self.manager.mark_developer_completed(task.id, result.data)
                failed = False
            else:
                self.manager.mark_failed(task.id, result.message)
                failed = True
        except Exception as exc:
            self.manager.mark_failed(task.id, str(exc))
            failed = True

        events = compacting_llm.compaction_events[before_events:]
        return RealDeveloperTaskMetrics(
            task_id=task.id,
            developer_id=developer_id,
            duration_seconds=perf_counter() - started,
            llm_calls=binding.llm.stats.calls - before_calls,
            input_tokens=binding.llm.stats.input_tokens - before_input,
            output_tokens=binding.llm.stats.output_tokens - before_output,
            llm_latency_seconds=binding.llm.stats.latency_seconds - before_latency,
            tool_calls=tool_calls,
            test_commands=test_commands,
            failed=failed,
            llm_profiles=tuple(binding.llm.stats.profiles[before_profiles:]),
            compaction_count=sum(1 for event in events if event["compacted"]),
            max_prompt_chars_before_compaction=max((int(event["prompt_chars_before"]) for event in events), default=0),
            max_prompt_chars_after_compaction=max((int(event["prompt_chars_after"]) for event in events), default=0),
            max_context_messages_before_compaction=max((int(event["messages_before"]) for event in events), default=0),
            max_context_messages_after_compaction=max((int(event["messages_after"]) for event in events), default=0),
        )
