from runtime.tool_loop_batch import classify_safe_tool_batch


def test_read_only_filesystem_calls_are_safe_to_batch():
    decision = classify_safe_tool_batch(
        [
            {"name": "list_files", "arguments": {"path": "."}},
            {"name": "read_file", "arguments": {"path": "README.md"}},
        ]
    )

    assert decision.safe is True


def test_single_call_is_not_a_batch():
    decision = classify_safe_tool_batch(
        [{"name": "read_file", "arguments": {"path": "README.md"}}]
    )

    assert decision.safe is False


def test_mutating_or_execution_calls_reject_the_whole_batch():
    decision = classify_safe_tool_batch(
        [
            {"name": "read_file", "arguments": {"path": "README.md"}},
            {"name": "write_file", "arguments": {"path": "x.txt", "content": "x"}},
        ]
    )

    assert decision.safe is False


def test_unknown_or_malformed_calls_reject_the_whole_batch():
    assert not classify_safe_tool_batch(
        [
            {"name": "read_file", "arguments": {}},
            {"name": "future_tool", "arguments": {}},
        ]
    ).safe
    assert not classify_safe_tool_batch(
        [
            {"name": "read_file", "arguments": {}},
            {"name": "list_files", "arguments": "not-a-mapping"},
        ]
    ).safe


def test_batch_classifier_does_not_reorder_calls():
    calls = [
        {"name": "read_file", "arguments": {"path": "a.py"}},
        {"name": "list_files", "arguments": {"path": "src"}},
    ]

    decision = classify_safe_tool_batch(calls)

    assert decision.safe is True
    assert [call["name"] for call in calls] == ["read_file", "list_files"]
