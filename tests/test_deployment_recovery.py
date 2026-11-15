from __future__ import annotations

import pytest

from runtime.deployment_recovery import classify_replacement_recovery
from runtime.deployment_replacement import ReplacementJournalRecord


def record(phase, **overrides):
    values = {
        "operation_id": "replace-001",
        "provider": "docker-local",
        "project": "demo",
        "environment": "staging",
        "target_deployment_id": "target",
        "previous_deployment_id": "previous",
        "phase": phase,
        "created_at": "2026-11-15T10:00:00Z",
        "updated_at": "2026-11-15T10:00:00Z",
        "candidate_runtime_id": "runtime-candidate",
        "previous_runtime_id": "runtime-previous",
    }
    values.update(overrides)
    return ReplacementJournalRecord(**values)


@pytest.mark.parametrize("phase", ["prepared", "candidate_started"])
def test_pre_switch_crash_requires_provider_inspection_and_never_auto_aborts(phase):
    assessment = classify_replacement_recovery(record(phase))
    assert assessment.disposition == "pre_switch_state_requires_inspection"
    assert "inspect_provider_operation_by_operation_id" in assessment.required_checks or (
        "inspect_candidate_and_previous_by_immutable_runtime_identity"
        in assessment.required_checks
    )
    assert assessment.automatic_action == "none"


def test_candidate_healthy_requires_fresh_health_and_route_readback():
    assessment = classify_replacement_recovery(record("candidate_healthy"))
    assert assessment.disposition == "candidate_health_and_route_require_verification"
    assert "freshly_verify_candidate_health" in assessment.required_checks
    assert "read_back_effective_traffic_target" in assessment.required_checks


def test_traffic_switched_requires_route_readback_before_retirement():
    assessment = classify_replacement_recovery(record("traffic_switched"))
    assert assessment.disposition == "route_readback_required_before_retire"
    assert assessment.required_checks.index("read_back_effective_traffic_target") < (
        assessment.required_checks.index("confirm_previous_runtime_identity_before_retirement")
    )
    assert assessment.automatic_action == "none"


def test_needs_reconciliation_requires_manual_review():
    assessment = classify_replacement_recovery(record("needs_reconciliation"))
    assert assessment.disposition == "manual_reconciliation_required"
    assert "record_explicit_reconciliation_decision" in assessment.required_checks


@pytest.mark.parametrize("phase", ["previous_retired", "aborted"])
def test_terminal_phases_require_no_recovery_action(phase):
    assessment = classify_replacement_recovery(record(phase))
    assert assessment.disposition == "terminal_no_recovery_action"
    assert assessment.required_checks == ()
    assert assessment.automatic_action == "none"


def test_missing_runtime_identities_are_reported_not_inferred():
    assessment = classify_replacement_recovery(record(
        "traffic_switched", candidate_runtime_id=None, previous_runtime_id=None
    ))
    assert assessment.missing_runtime_identities == (
        "candidate_runtime_id", "previous_runtime_id"
    )
    assert assessment.disposition == "route_readback_required_before_retire"
