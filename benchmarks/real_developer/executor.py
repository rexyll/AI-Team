from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

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

    def __init__(self, manager: TaskManager, developer_count: int, *, llm_factory: Callable[[], BaseLLM], config_factory: Callable[[int], AgentConfig | None] | None = None) -> None:
        if developer_count <= 0:
            raise ValueError("developer_count must be greater than 0")
        self.manager = manager
        self.developer_count = developer_count
        self._bindings: list[_DeveloperBinding] = []
        for index in range(developer_count):
            llm = InstrumentedLLM(llm_factory())
            config = config_factory(index + 1) if config_factory else None
            compacting_llm = ContextCompactingLLM(llm)
            self._bindings.append(_DeveloperBinding(developer_id=f"developer-{index + 1}", agent=DeveloperAgent(config=config, llm=compacting_llm), llm=llm))

    @staticmethod
    def _recover_partial_tool_telemetry(agent: DeveloperAgent, task_id: str) -> tuple[dict[str, Any], ...]:
        history = getattr(agent, "tool_execution_history", None)
        if history is None or not hasattr(history, "list_for_task"):
            return ()
        try:
            records = history.list_for_task(task_id)
        except Exception:
            return ()
        telemetry: list[dict[str, Any]] = []
        for record in records:
            item = dict(getattr(record, "metadata", {}) or {})
            item.setdefault("execution_id", record.execution_id)
            item.setdefault("tool_name", record.tool_name)
            item.setdefault("arguments_hash", "")
            item.setdefault("result_hash", "")
            item.setdefault("result_chars", len(str(record.output or "")))
            item.setdefault("retained_result_chars", item["result_chars"])
            item.setdefault("result_truncated", False)
            item.setdefault("duplicate_of", None)
            item.setdefault("retry_of", None)
            item.setdefault("category", "other")
            telemetry.append(item)
        return tuple(telemetry)

    @classmethod
    def _metrics_from_partial_history(
        cls,
        agent: DeveloperAgent,
        task_id: str,
    ) -> tuple[int, int, int, int, int, int, tuple[dict[str, Any], ...]]:
        telemetry = cls._recover_partial_tool_telemetry(agent, task_id)
        tool_calls = len(telemetry)
        duplicate_tool_calls = sum(1 for item in telemetry if item.get("duplicate_of"))
        retry_tool_calls = sum(1 for item in telemetry if item.get("retry_of"))
        unique_tool_calls = max(0, tool_calls - duplicate_tool_calls)
        test_commands = sum(1 for item in telemetry if item.get("tool_name") == "run_command")
        tool_result_chars = sum(int(item.get("result_chars", 0) or 0) for item in telemetry)
        largest_tool_result_chars = max((int(item.get("result_chars", 0) or 0) for item in telemetry), default=0)
        return tool_calls, test_commands, unique_tool_calls, duplicate_tool_calls, retry_tool_calls, tool_result_chars, telemetry

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
        cache_hits = cache_misses = cache_invalidations = 0
        tool_calls = test_commands = unique_tool_calls = duplicate_tool_calls = retry_tool_calls = 0
        tool_result_chars = largest_tool_result_chars = 0
        tool_loop_telemetry: tuple[dict, ...] = ()
        developer_decision_trace: tuple[dict, ...] = ()
        failure_reason: str | None = None
        failure_stage: str | None = None
        failed = False
        result = None

        try:
            self.manager.mark_running(task.id)
            result = binding.agent.run(task)
            validation = result.data.get("validation", {}) if isinstance(result.data, dict) else {}
            cache_data = result.data.get("tool_loop_cache", {}) if isinstance(result.data, dict) else {}
            raw_telemetry = result.data.get("tool_loop_telemetry", ()) if isinstance(result.data, dict) else ()
            raw_decision_trace = result.data.get("developer_decision_trace", ()) if isinstance(result.data, dict) else ()
            tool_loop_telemetry = tuple(item for item in raw_telemetry if isinstance(item, dict))
            developer_decision_trace = tuple(item for item in raw_decision_trace if isinstance(item, dict))
            tool_calls = int(validation.get("tool_call_count", 0) or 0)
            test_commands = int(validation.get("test_command_count", 0) or 0)
            unique_tool_calls = int(validation.get("unique_tool_calls", 0) or 0)
            duplicate_tool_calls = int(validation.get("duplicate_tool_calls", 0) or 0)
            retry_tool_calls = int(validation.get("retry_tool_calls", 0) or 0)
            tool_result_chars = int(validation.get("tool_result_chars", 0) or 0)
            largest_tool_result_chars = int(validation.get("largest_tool_result_chars", 0) or 0)
            cache_hits = int(cache_data.get("hits", 0) or 0)
            cache_misses = int(cache_data.get("misses", 0) or 0)
            cache_invalidations = int(cache_data.get("invalidations", 0) or 0)
            if result.status == "completed":
                try:
                    self.manager.mark_developer_completed(task.id, result.data)
                except Exception as exc:
                    failure_reason = f"{type(exc).__name__}: {exc}"
                    failure_stage = "task_manager_transition"
                    failed = True
                else:
                    failed = False
            else:
                failure_reason = str(result.message or "Developer returned failed status")
                failure_stage = "agent_result"
                self.manager.mark_failed(task.id, failure_reason)
                failed = True
        except Exception as exc:
            failure_reason = f"{type(exc).__name__}: {exc}"
            failure_stage = "agent_run" if result is None else "task_manager_transition"
            failed = True
            if result is None or not tool_loop_telemetry:
                (
                    tool_calls,
                    test_commands,
                    unique_tool_calls,
                    duplicate_tool_calls,
                    retry_tool_calls,
                    tool_result_chars,
                    tool_loop_telemetry,
                ) = self._metrics_from_partial_history(binding.agent, task.id)
                largest_tool_result_chars = max((int(item.get("result_chars", 0) or 0) for item in tool_loop_telemetry), default=0)
            try:
                self.manager.mark_failed(task.id, failure_reason)
            except Exception:
                pass

        events = compacting_llm.compaction_events[before_events:]
        return RealDeveloperTaskMetrics(
            task_id=task.id, developer_id=developer_id, duration_seconds=perf_counter() - started,
            llm_calls=binding.llm.stats.calls - before_calls, input_tokens=binding.llm.stats.input_tokens - before_input,
            output_tokens=binding.llm.stats.output_tokens - before_output, llm_latency_seconds=binding.llm.stats.latency_seconds - before_latency,
            tool_calls=tool_calls, test_commands=test_commands, unique_tool_calls=unique_tool_calls,
            duplicate_tool_calls=duplicate_tool_calls, retry_tool_calls=retry_tool_calls, tool_result_chars=tool_result_chars,
            largest_tool_result_chars=largest_tool_result_chars, cache_hits=cache_hits, cache_misses=cache_misses,
            cache_invalidations=cache_invalidations, failed=failed, failure_reason=failure_reason, failure_stage=failure_stage,
            llm_profiles=tuple(binding.llm.stats.profiles[before_profiles:]),
            tool_loop_telemetry=tool_loop_telemetry,
            developer_decision_trace=developer_decision_trace,
            compaction_count=sum(1 for event in events if event["compacted"]),
            max_prompt_chars_before_compaction=max((int(event["prompt_chars_before"]) for event in events), default=0),
            max_prompt_chars_after_compaction=max((int(event["prompt_chars_after"]) for event in events), default=0),
            max_context_messages_before_compaction=max((int(event["messages_before"]) for event in events), default=0),
            max_context_messages_after_compaction=max((int(event["messages_after"]) for event in events), default=0),
        )
