from __future__ import annotations

from runtime.context_compaction import ContextCompactionConfig, ContextCompactor, estimate_tokens


def test_compactor_enforces_character_and_token_budgets() -> None:
    compactor = ContextCompactor(ContextCompactionConfig(max_prompt_chars=1200, max_input_tokens_per_call=600))
    messages = [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "U" * 900},
        {"role": "assistant", "content": "A" * 900},
        {"role": "tool", "tool_call_id": "call-1", "content": "T" * 1800},
        {"role": "user", "content": "latest request"},
    ]
    compacted, stats = compactor.compact_messages(messages)
    total_chars = sum(len(str(message.get("content", ""))) for message in compacted)
    total_tokens = sum(estimate_tokens(str(message.get("content", ""))) for message in compacted)
    assert total_chars <= 1200
    assert total_tokens <= 600
    assert stats.original_chars > stats.compacted_chars
    assert stats.truncated_messages >= 1
    assert compacted[-1]["content"] == "latest request"
    assert compacted[3]["tool_call_id"] == "call-1"


def test_compactor_preserves_tool_call_protocol_metadata() -> None:
    compactor = ContextCompactor(ContextCompactionConfig(max_prompt_chars=500, max_input_tokens_per_call=250))
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "assistant reasoning " * 100, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "tool output " * 100},
    ]
    compacted, _ = compactor.compact_messages(messages)
    assert compacted[1]["tool_calls"][0]["id"] == "call-1"
    assert compacted[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert compacted[2]["tool_call_id"] == "call-1"


def test_prompt_compaction_reports_original_and_compacted_sizes() -> None:
    compactor = ContextCompactor(ContextCompactionConfig(max_prompt_chars=400, max_input_tokens_per_call=200))
    prompt, system, stats = compactor.compact_prompt("request " * 200, system_prompt="stable system instructions")
    assert system == "stable system instructions"
    assert len(prompt) + len(system) <= 400
    assert stats.original_chars > stats.compacted_chars
    assert stats.growth_ratio < 1.0
