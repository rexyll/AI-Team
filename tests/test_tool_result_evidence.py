from runtime.tool_result_evidence import reduce_tool_result


def test_small_result_is_preserved_exactly() -> None:
    evidence = reduce_tool_result("read_file", "small result", max_chars=100)
    assert evidence.content == "small result"
    assert evidence.original_chars == evidence.retained_chars
    assert evidence.truncated is False


def test_read_file_keeps_head_and_tail_with_marker() -> None:
    source = "HEAD\n" + ("x" * 500) + "\nTAIL"
    evidence = reduce_tool_result("read_file", source, max_chars=120)

    assert evidence.truncated is True
    assert evidence.original_chars == len(source)
    assert evidence.retained_chars <= 120
    assert evidence.content.startswith("HEAD")
    assert evidence.content.endswith("TAIL")
    assert "tool evidence truncated" in evidence.content


def test_command_output_prioritizes_tail() -> None:
    source = "early setup output\n" + ("noise\n" * 500) + "FAILED test_example - assertion details"
    evidence = reduce_tool_result("run_command", source, max_chars=200)

    assert evidence.truncated is True
    assert evidence.content.endswith("FAILED test_example - assertion details")
    assert evidence.retained_chars <= 200
    assert "tool evidence truncated" in evidence.content


def test_generic_tool_result_is_bounded() -> None:
    source = "x" * 10_000
    evidence = reduce_tool_result("other_tool", source, max_chars=500)

    assert evidence.truncated is True
    assert evidence.retained_chars <= 500
    assert evidence.original_chars == 10_000


def test_structured_results_are_rendered_deterministically() -> None:
    first = reduce_tool_result("list_files", {"b": 2, "a": 1}, max_chars=100)
    second = reduce_tool_result("list_files", {"a": 1, "b": 2}, max_chars=100)

    assert first.content == second.content == '{"a": 1, "b": 2}'
    assert first.truncated is False


def test_read_file_budget_is_exact_even_when_marker_is_large() -> None:
    evidence = reduce_tool_result("read_file", "x" * 10_000, max_chars=20)

    assert evidence.truncated is True
    assert evidence.retained_chars == 20
    assert len(evidence.content) == 20


def test_invalid_budget_is_rejected() -> None:
    try:
        reduce_tool_result("read_file", "value", max_chars=0)
    except ValueError as exc:
        assert "max_chars" in str(exc)
    else:
        raise AssertionError("expected invalid evidence budget to be rejected")
