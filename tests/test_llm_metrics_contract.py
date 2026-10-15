from __future__ import annotations

from runtime.llm_metrics import LLMMetrics


def test_llm_metrics_tracks_calls_tools_and_context_growth() -> None:
    metrics = LLMMetrics()
    metrics.record_llm_call(prompt_chars=1000, input_tokens=250, elapsed_seconds=0.02)
    metrics.record_tool_calls(2)
    metrics.record_llm_call(prompt_chars=1500, input_tokens=400, elapsed_seconds=0.03)
    metrics.record_tool_calls(1)
    metrics.finish(wall_seconds=0.10)
    snapshot = metrics.snapshot()
    assert snapshot.llm_calls == 2
    assert snapshot.tool_calls == 3
    assert snapshot.max_prompt_chars == 1500
    assert snapshot.max_input_tokens_per_call == 400
    assert snapshot.initial_prompt_chars == 1000
    assert snapshot.context_growth_ratio == 1.5
    assert snapshot.llm_time_ratio == 0.5


def test_llm_metrics_zero_duration_is_safe() -> None:
    metrics = LLMMetrics()
    metrics.record_llm_call(prompt_chars=10, input_tokens=3, elapsed_seconds=0.0)
    metrics.finish(wall_seconds=0.0)
    assert metrics.snapshot().llm_time_ratio == 0.0
