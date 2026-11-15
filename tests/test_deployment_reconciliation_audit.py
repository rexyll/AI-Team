from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from runtime.deployment_reconciliation_audit import (
    ReconciliationAuditEnvelope,
    _ZERO_DIGEST,
)
from runtime.deployment_reconciliation_contract import AuthenticatedPrincipal


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="operator-1",
        issuer="test-host-auth",
        authentication_method="test-signed-assertion",
        authenticated_at="2026-11-15T10:00:00+00:00",
    )


def _event(
    *,
    sequence: int = 1,
    previous_digest: str = _ZERO_DIGEST,
    event_id: str = "event-1",
) -> ReconciliationAuditEnvelope:
    values = {
        "event_id": event_id,
        "sequence": sequence,
        "previous_digest": previous_digest,
        "action": "reconciliation_proposed",
        "actor": _principal(),
        "approval_id": "approval-1",
        "operation_id": "operation-1",
        "provider": "docker",
        "project": "project-a",
        "environment": "staging",
        "journal_phase": "needs_reconciliation",
        "target_deployment_id": "deployment-candidate",
        "previous_deployment_id": "deployment-previous",
        "candidate_runtime_id": "container-candidate",
        "previous_runtime_id": "container-previous",
        "proposal_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "recorded_at": "2026-11-15T10:01:00+00:00",
    }
    provisional = ReconciliationAuditEnvelope.__new__(ReconciliationAuditEnvelope)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = sha256(provisional.canonical_payload()).hexdigest()
    return ReconciliationAuditEnvelope(**values, event_digest=digest)


def test_valid_first_audit_envelope_has_canonical_digest() -> None:
    event = _event()
    assert event.sequence == 1
    assert event.previous_digest == _ZERO_DIGEST
    assert event.event_digest == sha256(event.canonical_payload()).hexdigest()


def test_successor_must_link_to_prior_event_and_increment_sequence() -> None:
    first = _event()
    second = _event(
        sequence=2,
        previous_digest=first.event_digest,
        event_id="event-2",
    )
    second.verify_successor_of(first)


def test_successor_rejects_broken_link_and_sequence() -> None:
    first = _event()
    wrong_link = _event(sequence=2, previous_digest="c" * 64, event_id="event-2")
    with pytest.raises(ValueError, match="previous_digest"):
        wrong_link.verify_successor_of(first)
    wrong_sequence = _event(
        sequence=3,
        previous_digest=first.event_digest,
        event_id="event-3",
    )
    with pytest.raises(ValueError, match="sequence"):
        wrong_sequence.verify_successor_of(first)


def test_event_digest_detects_payload_tampering() -> None:
    event = _event()
    with pytest.raises(ValueError, match="event_digest"):
        replace(event, project="project-tampered")


def test_invalid_digest_action_and_timestamp_fail_closed() -> None:
    event = _event()
    with pytest.raises(ValueError, match="proposal_digest"):
        replace(event, proposal_digest="not-a-digest")
    with pytest.raises(ValueError, match="action"):
        replace(event, action="unlock_scope")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(event, recorded_at="2026-11-15T10:01:00")


def test_non_first_event_requires_nonzero_previous_digest() -> None:
    with pytest.raises(ValueError, match="non-first"):
        _event(sequence=2)
