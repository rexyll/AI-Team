from __future__ import annotations

import pytest

from runtime.deployment_replacement import ReplacementJournalRecord


def make_journal(**overrides):
    values = {
        "operation_id": "replace-001",
        "provider": "docker-local",
        "project": "demo",
        "environment": "staging",
        "target_deployment_id": "release-old",
        "previous_deployment_id": "release-current",
        "phase": "prepared",
        "created_at": "2026-11-15T10:00:00Z",
        "updated_at": "2026-11-15T10:00:00Z",
    }
    values.update(overrides)
    return ReplacementJournalRecord(**values)


def test_replacement_journal_records_both_deployments_and_phase():
    record = make_journal(
        phase="candidate_healthy",
        candidate_runtime_id="runtime-candidate-immutable",
        previous_runtime_id="runtime-current-immutable",
    )
    assert record.target_deployment_id == "release-old"
    assert record.previous_deployment_id == "release-current"
    assert record.candidate_runtime_id == "runtime-candidate-immutable"
    assert record.phase == "candidate_healthy"


@pytest.mark.parametrize(
    "phase",
    [
        "prepared",
        "candidate_started",
        "candidate_healthy",
        "traffic_switched",
        "previous_retired",
        "aborted",
        "needs_reconciliation",
    ],
)
def test_replacement_journal_accepts_known_phases(phase):
    assert make_journal(phase=phase).phase == phase


def test_replacement_journal_rejects_unknown_phase():
    with pytest.raises(ValueError, match="phase"):
        make_journal(phase="completed_without_evidence")


def test_replacement_journal_rejects_same_target_and_previous_deployment():
    with pytest.raises(ValueError, match="must differ"):
        make_journal(previous_deployment_id="release-old")


@pytest.mark.parametrize(
    "field",
    ["operation_id", "provider", "project", "environment", "target_deployment_id",
     "previous_deployment_id", "created_at", "updated_at"],
)
def test_replacement_journal_requires_scope_and_timestamps(field):
    with pytest.raises(ValueError, match="non-empty"):
        make_journal(**{field: "  "})


@pytest.mark.parametrize(
    "field",
    ["candidate_runtime_id", "previous_runtime_id", "effective_traffic_target"],
)
def test_replacement_journal_rejects_empty_optional_identity(field):
    with pytest.raises(ValueError, match="non-empty"):
        make_journal(**{field: ""})
