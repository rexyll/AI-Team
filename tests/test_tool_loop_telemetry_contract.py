from runtime.tool_loop_telemetry import classify_tool_call, stable_hash


def test_stable_hash_is_order_independent_for_json_objects() -> None:
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_first_tool_call_has_no_duplicate_or_retry() -> None:
    telemetry = classify_tool_call(tool_name="read_file", arguments={"path": "a.py"}, result="hello", prior=[])
    assert telemetry.duplicate_of is None
    assert telemetry.retry_of is None
    assert telemetry.result_chars == 5


def test_same_tool_and_arguments_are_classified_as_duplicate() -> None:
    first = classify_tool_call(tool_name="read_file", arguments={"path": "a.py"}, result="hello", prior=[])
    second = classify_tool_call(tool_name="read_file", arguments={"path": "a.py"}, result="hello", prior=[("EXEC-1", "read_file", first.arguments_hash, "completed")])
    assert second.duplicate_of == "EXEC-1"
    assert second.retry_of is None


def test_same_tool_and_arguments_after_failure_are_classified_as_retry() -> None:
    first = classify_tool_call(tool_name="run_command", arguments={"command": "pytest -q"}, result="failed", prior=[])
    second = classify_tool_call(tool_name="run_command", arguments={"command": "pytest -q"}, result="passed", prior=[("EXEC-1", "run_command", first.arguments_hash, "failed")])
    assert second.duplicate_of == "EXEC-1"
    assert second.retry_of == "EXEC-1"
