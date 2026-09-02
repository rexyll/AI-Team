from __future__ import annotations

import pytest

from mcp_bridge.observability import MCPOperationTracker


def test_operation_tracker_correlates_request_and_operation() -> None:
    tracker = MCPOperationTracker()
    started = tracker.start(
        "terminal_execute",
        policy_profile="developer",
        policy_allowed=True,
        request_id="req-1",
        project_id="project-1",
    )

    finished = tracker.finish(
        started.operation_id,
        outcome="success",
        execution_id="exec-1",
        metadata={"exit_code": 0},
    )

    assert finished.request_id == "req-1"
    assert finished.operation_id == started.operation_id
    assert finished.execution_id == "exec-1"
    assert finished.outcome == "success"
    assert finished.duration_ms is not None
    assert finished.duration_ms >= 0
    assert finished.metadata["exit_code"] == 0


def test_operation_tracker_keeps_history_bounded() -> None:
    tracker = MCPOperationTracker(max_records=2)
    first = tracker.start("workspace_read_file", policy_profile="readonly", policy_allowed=True)
    tracker.start("workspace_list_files", policy_profile="readonly", policy_allowed=True)
    third = tracker.start("git_status", policy_profile="readonly", policy_allowed=True)

    assert tracker.get(first.operation_id) is None
    history = tracker.history(limit=2)
    assert len(history) == 2
    assert history[0]["operation_id"] == third.operation_id


def test_operation_tracker_rejects_invalid_limits() -> None:
    tracker = MCPOperationTracker(max_records=2)
    with pytest.raises(ValueError):
        tracker.history(limit=3)
