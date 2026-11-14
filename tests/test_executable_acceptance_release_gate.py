from __future__ import annotations

from runtime.release_gate import evaluate_release_gate


def test_release_gate_blocks_failed_executable_acceptance():
    result = evaluate_release_gate(
        integration={"status": "passed"},
        acceptance={"verdict": "failed", "gaps": ["REQ-001 has no executable acceptance test"]},
    )

    assert result["status"] == "blocked"
    assert result["blockers"] == [{
        "code": "acceptance_failed",
        "reason": "可执行需求验收证据未通过或未执行",
    }]


def test_release_gate_blocks_not_executed_acceptance():
    result = evaluate_release_gate(
        acceptance={"verdict": "not_executed", "gaps": ["AT-001 not_executed"]},
    )

    assert result["status"] == "blocked"
    assert result["blockers"][0]["code"] == "acceptance_failed"


def test_release_gate_allows_passing_executable_acceptance():
    result = evaluate_release_gate(
        integration={"status": "passed"},
        acceptance={"verdict": "passed", "gaps": []},
    )

    assert result == {"status": "allowed", "blockers": []}


def test_release_gate_keeps_acceptance_optional_for_legacy_projects():
    result = evaluate_release_gate(integration={"status": "passed"})

    assert result == {"status": "allowed", "blockers": []}
