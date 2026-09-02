from __future__ import annotations

from web_host_bridge.observability import MCPOperationTracker


def test_operation_record_has_stable_correlation_contract() -> None:
    tracker = MCPOperationTracker()
    record = tracker.start(
        "git_status",
        policy_profile="readonly",
        policy_allowed=True,
        request_id="req-fixed",
        project_id="project-fixed",
        execution_id="exec-fixed",
    )
    data = record.as_dict()

    assert set(("request_id", "operation_id", "capability", "policy_profile", "policy_allowed", "started_at", "project_id", "execution_id", "finished_at", "duration_ms", "outcome", "error_type", "metadata")) <= set(data)
    assert data["request_id"] == "req-fixed"
    assert data["execution_id"] == "exec-fixed"
