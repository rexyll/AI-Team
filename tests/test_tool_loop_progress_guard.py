import pytest

from runtime.tool_loop_progress_guard import (
    ToolLoopProgressGuard,
    ToolLoopProgressGuardConfig,
)


def test_guard_trips_after_consecutive_exact_duplicates():
    guard = ToolLoopProgressGuard(ToolLoopProgressGuardConfig(max_consecutive_duplicates=3))

    assert guard.record(tool_name="read_file", status="completed", duplicate_of=None, retry_of=None) is None
    assert guard.record(tool_name="read_file", status="completed", duplicate_of="1", retry_of=None) is None
    assert guard.record(tool_name="read_file", status="completed", duplicate_of="2", retry_of=None) is None
    reason = guard.record(tool_name="read_file", status="completed", duplicate_of="3", retry_of=None)

    assert reason is not None
    assert "repeated exact tool call" in reason
    assert guard.trip_reason == reason


def test_distinct_success_resets_duplicate_streak():
    guard = ToolLoopProgressGuard(ToolLoopProgressGuardConfig(max_consecutive_duplicates=2))

    guard.record(tool_name="read_file", status="completed", duplicate_of="1", retry_of=None)
    assert guard.record(tool_name="list_files", status="completed", duplicate_of=None, retry_of=None) is None
    assert guard.record(tool_name="read_file", status="completed", duplicate_of="2", retry_of=None) is None


def test_guard_trips_after_consecutive_failures_and_retry_is_still_failure():
    guard = ToolLoopProgressGuard(ToolLoopProgressGuardConfig(max_consecutive_failures=2))

    assert guard.record(tool_name="run_command", status="failed", duplicate_of=None, retry_of=None) is None
    reason = guard.record(tool_name="run_command", status="failed", duplicate_of="1", retry_of="1")

    assert reason is not None
    assert "repeated tool failures" in reason


def test_completed_call_resets_failure_streak():
    guard = ToolLoopProgressGuard(ToolLoopProgressGuardConfig(max_consecutive_failures=2))

    guard.record(tool_name="run_command", status="failed", duplicate_of=None, retry_of=None)
    assert guard.record(tool_name="read_file", status="completed", duplicate_of=None, retry_of=None) is None
    assert guard.record(tool_name="run_command", status="failed", duplicate_of=None, retry_of=None) is None


def test_config_rejects_non_positive_thresholds():
    with pytest.raises(ValueError):
        ToolLoopProgressGuardConfig(max_consecutive_duplicates=0)
    with pytest.raises(ValueError):
        ToolLoopProgressGuardConfig(max_consecutive_failures=0)
