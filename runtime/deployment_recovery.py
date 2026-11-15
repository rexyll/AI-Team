"""Read-only crash-recovery classification for deployment replacement journals.

This module never calls a provider, changes traffic, retires a runtime, or
mutates the journal. It translates a durable phase snapshot into checks that
an operator/reconciler must perform before taking any action.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from runtime.deployment_replacement import ReplacementJournalRecord

RecoveryDisposition = Literal[
    "pre_switch_state_requires_inspection",
    "candidate_health_and_route_require_verification",
    "route_readback_required_before_retire",
    "manual_reconciliation_required",
    "terminal_no_recovery_action",
]


@dataclass(frozen=True)
class ReplacementRecoveryAssessment:
    """A conservative, side-effect-free recovery assessment."""

    operation_id: str
    phase: str
    disposition: RecoveryDisposition
    required_checks: tuple[str, ...]
    missing_runtime_identities: tuple[str, ...]
    automatic_action: Literal["none"] = "none"


def classify_replacement_recovery(
    record: ReplacementJournalRecord,
) -> ReplacementRecoveryAssessment:
    """Classify a journal snapshot without inferring provider or traffic state.

    A crash may occur after a provider side effect but before its journal
    transition. Therefore even early phases require fresh provider inspection;
    no phase authorizes automatic abort, route mutation, or runtime retirement.
    """
    missing = tuple(
        name
        for name, value in (
            ("candidate_runtime_id", record.candidate_runtime_id),
            ("previous_runtime_id", record.previous_runtime_id),
        )
        if value is None
    )

    if record.phase == "prepared":
        disposition: RecoveryDisposition = "pre_switch_state_requires_inspection"
        checks = (
            "inspect_provider_operation_by_operation_id",
            "resolve_candidate_and_previous_immutable_runtime_identity",
            "verify_effective_traffic_target_before_any_mutation",
        )
    elif record.phase == "candidate_started":
        disposition = "pre_switch_state_requires_inspection"
        checks = (
            "inspect_candidate_and_previous_by_immutable_runtime_identity",
            "freshly_verify_candidate_health",
            "verify_effective_traffic_target_before_any_mutation",
        )
    elif record.phase == "candidate_healthy":
        disposition = "candidate_health_and_route_require_verification"
        checks = (
            "freshly_verify_candidate_health",
            "read_back_effective_traffic_target",
            "confirm_previous_runtime_remains_available",
        )
    elif record.phase == "traffic_switched":
        disposition = "route_readback_required_before_retire"
        checks = (
            "read_back_effective_traffic_target",
            "confirm_route_targets_candidate_immutable_runtime_identity",
            "freshly_verify_candidate_health",
            "confirm_previous_runtime_identity_before_retirement",
        )
    elif record.phase == "needs_reconciliation":
        disposition = "manual_reconciliation_required"
        checks = (
            "operator_review_provider_operation_and_immutable_runtime_identities",
            "read_back_effective_traffic_target",
            "record_explicit_reconciliation_decision",
        )
    else:
        disposition = "terminal_no_recovery_action"
        checks = ()

    return ReplacementRecoveryAssessment(
        operation_id=record.operation_id,
        phase=record.phase,
        disposition=disposition,
        required_checks=checks,
        missing_runtime_identities=missing,
    )
