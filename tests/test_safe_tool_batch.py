from runtime.safe_tool_batch import classify_safe_tool_batch


def _call(name: str, **arguments):
    return {"name": name, "arguments": arguments}


def test_independent_read_file_calls_are_safe():
    decision = classify_safe_tool_batch([
        _call("read_file", path="a.py"),
        _call("read_file", path="b.py"),
    ])
    assert decision.safe is True
    assert decision.reason == "independent_read_only_calls"


def test_independent_list_files_calls_are_safe():
    decision = classify_safe_tool_batch([
        _call("list_files", path="src"),
        _call("list_files", path="tests"),
    ])
    assert decision.safe is True


def test_duplicate_read_only_call_is_not_a_batch():
    decision = classify_safe_tool_batch([
        _call("read_file", path="a.py"),
        _call("read_file", path="a.py"),
    ])
    assert decision.safe is False
    assert decision.reason == "duplicate_read_only_call"


def test_list_files_and_read_file_are_not_assumed_independent():
    decision = classify_safe_tool_batch([
        _call("list_files", path="src"),
        _call("read_file", path="src/main.py"),
    ])
    assert decision.safe is False
    assert decision.reason == "cross_tool_dependency_possible"


def test_mutation_tool_is_never_safe_to_batch():
    decision = classify_safe_tool_batch([
        _call("read_file", path="a.py"),
        _call("write_file", path="b.py", content="x"),
    ])
    assert decision.safe is False
    assert decision.reason == "contains_non_read_only_tool"


def test_command_tool_is_never_safe_to_batch():
    decision = classify_safe_tool_batch([
        _call("read_file", path="a.py"),
        _call("run_command", command="pytest -q"),
    ])
    assert decision.safe is False
    assert decision.reason == "contains_non_read_only_tool"
