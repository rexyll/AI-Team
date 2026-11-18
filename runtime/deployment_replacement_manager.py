"""Host-owned deployment replacement transaction coordinator.

A provider is eligible only when it can inspect immutable runtime identities,
perform traffic switching, and read the effective route back. Local Docker
currently lacks a traffic router and therefore deliberately remains unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Literal
from uuid import uuid4

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import (
    DeploymentOperationResult,
    DeploymentRecord,
    DeploymentRequest,
    DeploymentRuntimeInspection,
    HealthCheckResult,
)
from runtime.deployment_recovery import (
    ReplacementRecoveryAssessment,
    classify_replacement_recovery,
)
from runtime.deployment_replacement import (
    DeploymentReplacementProvider,
    DeploymentTrafficReadback,
    ReplacementJournalRecord,
)


ReplacementStatus = Literal["replaced", "failed", "needs_reconciliation", "unsupported"]


@dataclass(frozen=True)
class DeploymentReplacementResult:
    status: ReplacementStatus
    message: str
    operation_id: str | None = None
    phase: str | None = None
    record: DeploymentRecord | None = None

RecoveryInventoryClassification = Literal[
    "journal_history_consistent",
    "reconciliation_required",
    "prepared_candidate_not_persisted",
    "candidate_record_missing",
    "candidate_identity_not_committed",
    "active_pointer_missing",
    "active_pointer_mismatch",
    "journal_route_evidence_incomplete",
    "switch_intent_requires_inspection",
    "journal_history_incomplete",
    "previous_retired_commit_pending",
    "candidate_stopped_commit_pending",
]


@dataclass(frozen=True)
class DeploymentRecoveryInventoryItem:
    """Read-only host-history snapshot for one non-terminal replacement.

    This inventory deliberately does not inspect or mutate provider resources.
    A consistent SQLite snapshot is not proof that containers or traffic routes
    still match it; recovery always requires a later provider read-back and
    explicit host authorization.
    """

    operation_id: str
    provider: str
    project: str
    environment: str
    phase: str
    classification: RecoveryInventoryClassification
    previous_deployment_id: str
    target_deployment_id: str
    previous_record_present: bool
    candidate_record_present: bool
    active_deployment_id: str | None
    recovery_assessment: ReplacementRecoveryAssessment
    external_state_verified: bool = False
    automatic_recovery_allowed: bool = False


@dataclass(frozen=True)
class DeploymentRecoveryRuntimeInspectionItem:
    """Provider observations for an unfinished replacement; never a resolution."""

    operation_id: str
    phase: str
    previous_deployment_id: str
    target_deployment_id: str
    previous_record_present: bool
    candidate_record_present: bool
    previous_runtime_id: str | None
    candidate_runtime_id: str | None
    inspection_supported: bool
    previous_runtime: DeploymentRuntimeInspection | None
    candidate_runtime: DeploymentRuntimeInspection | None
    route_readback_status: Literal["not_available"] = "not_available"
    automatic_recovery_allowed: Literal[False] = False


ManualReconciliationAssessment = Literal[
    "switch_applied_before_journal_commit",
    "switch_not_observed_before_journal_commit",
    "route_matches_journal_and_active_pointer",
    "route_matches_active_pointer_journal_unresolved",
    "route_active_pointer_mismatch",
    "route_readback_unavailable",
    "route_readback_mismatch",
    "runtime_identity_unverified",
    "runtime_not_running",
    "runtime_health_unverified",
    "durable_inventory_incomplete",
]


@dataclass(frozen=True)
class DeploymentManualReconciliationReadbackItem:
    """Operator-facing external read-back; it never authorizes a mutation."""

    operation_id: str
    provider: str
    project: str
    environment: str
    phase: str
    inventory_classification: RecoveryInventoryClassification
    previous_deployment_id: str
    target_deployment_id: str
    durable_active_deployment_id: str | None
    previous_runtime: DeploymentRuntimeInspection
    candidate_runtime: DeploymentRuntimeInspection
    route_readback: DeploymentTrafficReadback | None
    assessment: ManualReconciliationAssessment
    required_checks: tuple[str, ...]
    detail: str
    automatic_action: Literal["none"] = "none"
    automatic_recovery_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        for name in (
            "operation_id", "provider", "project", "environment",
            "phase", "previous_deployment_id", "target_deployment_id",
            "detail",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.required_checks, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.required_checks
        ):
            raise ValueError("required_checks must be a tuple of non-empty strings")
        if self.automatic_action != "none" or self.automatic_recovery_allowed is not False:
            raise ValueError("manual reconciliation read-back must never authorize automatic action")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class HostDeploymentReplacementManager:
    """Run a durable blue/green replacement transaction under host ownership.

    The previous runtime is never retired until candidate health is fresh,
    traffic read-back identifies the candidate immutable runtime, and the host
    active pointer has been advanced with compare-and-swap. Any ambiguity after
    an external side effect leaves both runtimes intact and reserves the scope
    for manual reconciliation. The coordinator never guesses a rollback route.
    """

    _REQUIRED_METHODS = (
        "health_check",
        "immutable_runtime_id",
        "prepare_candidate",
        "start_candidate",
        "verify_candidate",
        "switch_traffic",
        "read_traffic_target",
        "retire_previous",
        "abort_candidate",
    )

    def __init__(
        self,
        provider: DeploymentReplacementProvider,
        history: DeploymentHistoryStore,
        *,
        clock: Callable[[], str] = _now,
        operation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        name = getattr(provider, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("provider must expose a non-empty name")
        if not isinstance(history, DeploymentHistoryStore):
            raise TypeError("history must be a DeploymentHistoryStore")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if operation_id_factory is not None and not callable(operation_id_factory):
            raise TypeError("operation_id_factory must be callable")
        self.provider = provider
        self.history = history
        self._clock = clock
        self._operation_id_factory = operation_id_factory or (lambda: uuid4().hex)

    def _supports_replacement(self) -> bool:
        return all(callable(getattr(self.provider, name, None)) for name in self._REQUIRED_METHODS)

    def _recovery_inventory_for_snapshots(self, snapshots):
        inventory: list[DeploymentRecoveryInventoryItem] = []
        for snapshot in snapshots:
            journal = snapshot.journal
            previous = snapshot.previous
            candidate = snapshot.candidate
            active_id = snapshot.active_deployment_id
            classification: RecoveryInventoryClassification

            if not snapshot.active_pointer_consistent:
                classification = "journal_history_incomplete"
            else:
                scope_matches = (
                    journal.provider == self.provider.name
                    and previous is not None
                    and previous.deployment_id == journal.previous_deployment_id
                    and previous.provider == journal.provider
                    and previous.project == journal.project
                    and previous.environment == journal.environment
                    and previous.status in {"running", "stopped"}
                    and isinstance(journal.previous_runtime_id, str)
                    and bool(journal.previous_runtime_id.strip())
                )
                candidate_scope_matches = candidate is None or (
                    candidate.deployment_id == journal.target_deployment_id
                    and candidate.provider == journal.provider
                    and candidate.project == journal.project
                    and candidate.environment == journal.environment
                    and candidate.status in {"running", "stopped"}
                )

                if not scope_matches or not candidate_scope_matches:
                    classification = "journal_history_incomplete"
                elif active_id is None:
                    classification = "active_pointer_missing"
                elif previous.status == "stopped":
                    # mark_stopped() commits only after an inspect-confirmed
                    # stop. A crash can occur before the terminal journal phase.
                    retirement_committed = (
                        journal.phase in {"traffic_switched", "needs_reconciliation"}
                        and candidate is not None
                        and journal.candidate_runtime_id is not None
                        and journal.candidate_runtime_id != journal.previous_runtime_id
                        and journal.effective_traffic_target == journal.candidate_runtime_id
                        and active_id == journal.target_deployment_id
                    )
                    classification = (
                        "previous_retired_commit_pending"
                        if retirement_committed
                        else "journal_history_incomplete"
                    )
                elif candidate is not None and candidate.status == "stopped":
                    # The pre-switch abort path can commit the stopped candidate
                    # record immediately before its terminal aborted journal phase.
                    abort_committed = (
                        journal.phase in {
                            "candidate_started", "candidate_healthy", "traffic_switch_pending", "needs_reconciliation"
                        }
                        and journal.candidate_runtime_id is not None
                        and journal.candidate_runtime_id != journal.previous_runtime_id
                        and active_id == journal.previous_deployment_id
                        and journal.effective_traffic_target in {
                            None, journal.previous_runtime_id
                        }
                    )
                    classification = (
                        "candidate_stopped_commit_pending"
                        if abort_committed
                        else "journal_history_incomplete"
                    )
                elif journal.phase == "prepared" and (
                    journal.candidate_runtime_id is not None
                    or journal.effective_traffic_target is not None
                ):
                    classification = "journal_history_incomplete"
                elif candidate is not None and (
                    journal.candidate_runtime_id is None
                    or journal.candidate_runtime_id == journal.previous_runtime_id
                ):
                    # Crash window: candidate history may have been committed
                    # before its immutable runtime ID was committed to journal.
                    classification = "candidate_identity_not_committed"
                elif candidate is None and journal.phase == "prepared":
                    # The provider call may or may not have started before the
                    # crash. The host cannot infer absence from missing history.
                    classification = "prepared_candidate_not_persisted"
                elif candidate is None:
                    classification = "candidate_record_missing"
                elif journal.phase == "traffic_switch_pending":
                    classification = (
                        "switch_intent_requires_inspection"
                        if active_id == journal.previous_deployment_id
                        else "active_pointer_mismatch"
                    )
                elif journal.phase == "traffic_switched" and (
                    journal.candidate_runtime_id is None
                    or journal.effective_traffic_target != journal.candidate_runtime_id
                ):
                    classification = "journal_route_evidence_incomplete"
                elif journal.phase == "needs_reconciliation":
                    if active_id not in {
                        journal.previous_deployment_id,
                        journal.target_deployment_id,
                    }:
                        classification = "active_pointer_mismatch"
                    else:
                        classification = "reconciliation_required"
                elif journal.phase == "traffic_switched":
                    classification = (
                        "journal_history_consistent"
                        if active_id == journal.target_deployment_id
                        else "active_pointer_mismatch"
                    )
                elif active_id != journal.previous_deployment_id:
                    classification = "active_pointer_mismatch"
                else:
                    classification = "journal_history_consistent"

            inventory.append(
                DeploymentRecoveryInventoryItem(
                    operation_id=journal.operation_id,
                    provider=journal.provider,
                    project=journal.project,
                    environment=journal.environment,
                    phase=journal.phase,
                    classification=classification,
                    previous_deployment_id=journal.previous_deployment_id,
                    target_deployment_id=journal.target_deployment_id,
                    previous_record_present=previous is not None,
                    candidate_record_present=candidate is not None,
                    active_deployment_id=active_id,
                    recovery_assessment=classify_replacement_recovery(journal),
                )
            )
        return tuple(inventory)

    def recovery_inventory(
        self,
        *,
        project: str | None = None,
        environment: str | None = None,
    ) -> tuple[DeploymentRecoveryInventoryItem, ...]:
        """Return the durable, provider-independent inventory without mutation."""
        snapshots = self.history.list_replacement_recovery_snapshots(
            provider=self.provider.name,
            project=project,
            environment=environment,
        )
        return self._recovery_inventory_for_snapshots(snapshots)

    def inspect_recovery_runtimes(
        self,
        *,
        project: str | None = None,
        environment: str | None = None,
    ) -> tuple[DeploymentRecoveryRuntimeInspectionItem, ...]:
        """Inspect recorded or journal-addressed runtimes without mutation.

        A runtime ID durably written to the journal can be inspected even when
        the corresponding DeploymentRecord has not yet been committed. If the
        journal also lacks an immutable ID, no mutable name lookup is attempted.
        """
        snapshots = self.history.list_replacement_recovery_snapshots(
            provider=self.provider.name,
            project=project,
            environment=environment,
        )
        inspector = getattr(self.provider, "inspect_runtime", None)
        identity_inspector = getattr(self.provider, "inspect_runtime_identity", None)
        inspection_supported = callable(inspector) or callable(identity_inspector)

        def unavailable_observation(
            deployment_id: str,
            runtime_id: str | None,
            *,
            status: str,
            detail: str,
        ) -> DeploymentRuntimeInspection:
            return DeploymentRuntimeInspection(
                provider=self.provider.name,
                deployment_id=deployment_id,
                expected_runtime_id=runtime_id,
                observed_runtime_id=None,
                identity_match=False,
                status=status,
                runtime_state="unknown",
                health_status="unavailable" if status == "unavailable" else "unknown",
                checked_at=self._clock(),
                probe="host provider inspection",
                detail=detail,
            )

        def inspect(
            record: DeploymentRecord | None,
            deployment_id: str,
            journal_runtime_id: str | None,
        ) -> DeploymentRuntimeInspection | None:
            history_runtime_id = record.container_id if record is not None else None
            if (
                history_runtime_id is not None
                and journal_runtime_id is not None
                and history_runtime_id != journal_runtime_id
            ):
                return unavailable_observation(
                    deployment_id,
                    journal_runtime_id,
                    status="invalid_response",
                    detail="Host history runtime ID does not match replacement journal identity",
                )
            expected_runtime_id = journal_runtime_id or history_runtime_id
            if not inspection_supported:
                return None
            try:
                if (
                    record is not None
                    and callable(inspector)
                    and (history_runtime_id is not None or journal_runtime_id is None)
                ):
                    observation = inspector(record)
                elif expected_runtime_id is not None and callable(identity_inspector):
                    observation = identity_inspector(deployment_id, expected_runtime_id)
                elif record is not None and callable(inspector):
                    observation = inspector(record)
                else:
                    return None
            except Exception as exc:
                return unavailable_observation(
                    deployment_id,
                    expected_runtime_id,
                    status="unavailable",
                    detail=f"Provider inspection raised {type(exc).__name__}",
                )
            if (
                not isinstance(observation, DeploymentRuntimeInspection)
                or observation.provider != self.provider.name
                or observation.deployment_id != deployment_id
                or observation.expected_runtime_id != expected_runtime_id
            ):
                return unavailable_observation(
                    deployment_id,
                    expected_runtime_id,
                    status="invalid_response",
                    detail="Provider inspection did not match the journal/history runtime identity",
                )
            return observation

        return tuple(
            DeploymentRecoveryRuntimeInspectionItem(
                operation_id=snapshot.journal.operation_id,
                phase=snapshot.journal.phase,
                previous_deployment_id=snapshot.journal.previous_deployment_id,
                target_deployment_id=snapshot.journal.target_deployment_id,
                previous_record_present=snapshot.previous is not None,
                candidate_record_present=snapshot.candidate is not None,
                previous_runtime_id=snapshot.journal.previous_runtime_id,
                candidate_runtime_id=snapshot.journal.candidate_runtime_id,
                inspection_supported=inspection_supported,
                previous_runtime=inspect(
                    snapshot.previous,
                    snapshot.journal.previous_deployment_id,
                    snapshot.journal.previous_runtime_id,
                ),
                candidate_runtime=inspect(
                    snapshot.candidate,
                    snapshot.journal.target_deployment_id,
                    snapshot.journal.candidate_runtime_id,
                ),
            )
            for snapshot in snapshots
        )

    def manual_reconciliation_readback(
        self,
        *,
        project: str | None = None,
        environment: str | None = None,
    ) -> tuple[DeploymentManualReconciliationReadbackItem, ...]:
        """Build an operator read-back from one durable DB snapshot plus live probes.

        This operation is deliberately read-only: it does not update journal
        phases, active deployment pointers, Router selectors, runtime state or
        scope reservations. An assessment is evidence for a human decision,
        never permission for automatic reconciliation.
        """
        snapshots = self.history.list_replacement_recovery_snapshots(
            provider=self.provider.name,
            project=project,
            environment=environment,
        )
        inventory = self._recovery_inventory_for_snapshots(snapshots)
        inventory_by_id = {item.operation_id: item for item in inventory}
        runtime_inspector = getattr(
            self.provider, "inspect_reconciliation_runtime", None
        )
        route_inspector = getattr(
            self.provider, "inspect_reconciliation_route", None
        )

        def unavailable_runtime(
            deployment_id: str,
            runtime_id: str | None,
            detail: str,
            *,
            status: str = "unavailable",
        ) -> DeploymentRuntimeInspection:
            return DeploymentRuntimeInspection(
                provider=self.provider.name,
                deployment_id=deployment_id,
                expected_runtime_id=runtime_id,
                observed_runtime_id=None,
                identity_match=False,
                status=status,
                runtime_state="unknown",
                health_status="unavailable" if status == "unavailable" else "unknown",
                checked_at=self._clock(),
                probe="manual reconciliation immutable runtime read-back",
                detail=detail[:700],
            )

        def inspect_runtime(deployment_id: str, runtime_id: str | None):
            if runtime_id is None:
                return unavailable_runtime(
                    deployment_id,
                    None,
                    "Replacement journal has no immutable runtime ID; mutable-name inspection is forbidden",
                    status="invalid_response",
                )
            if not callable(runtime_inspector):
                return unavailable_runtime(
                    deployment_id,
                    runtime_id,
                    "Provider does not expose an explicit read-only reconciliation runtime inspector",
                )
            try:
                observation = runtime_inspector(deployment_id, runtime_id)
            except Exception as exc:
                return unavailable_runtime(
                    deployment_id,
                    runtime_id,
                    f"Immutable runtime inspection raised {type(exc).__name__}",
                )
            if (
                not isinstance(observation, DeploymentRuntimeInspection)
                or observation.provider != self.provider.name
                or observation.deployment_id != deployment_id
                or observation.expected_runtime_id != runtime_id
            ):
                return unavailable_runtime(
                    deployment_id,
                    runtime_id,
                    "Provider runtime inspection did not match the exact journal identity",
                    status="invalid_response",
                )
            return observation

        results: list[DeploymentManualReconciliationReadbackItem] = []
        for snapshot in snapshots:
            journal = snapshot.journal
            item = inventory_by_id[journal.operation_id]
            previous_runtime = inspect_runtime(
                journal.previous_deployment_id, journal.previous_runtime_id
            )
            candidate_runtime = inspect_runtime(
                journal.target_deployment_id, journal.candidate_runtime_id
            )
            route_readback = None
            if callable(route_inspector):
                try:
                    observed_route = route_inspector(journal)
                except Exception as exc:
                    observed_route = None
                    route_error = (
                        f"Traffic read-back raised {type(exc).__name__}: "
                        f"{str(exc)[:500]}"
                    )
                else:
                    route_error = "Provider returned no valid traffic read-back"
                if (
                    isinstance(observed_route, DeploymentTrafficReadback)
                    and observed_route.provider == self.provider.name
                ):
                    route_readback = observed_route
                elif observed_route is not None:
                    route_error = "Provider traffic read-back did not match the replacement provider"
            else:
                route_error = "Provider does not expose a read-only reconciliation traffic inspector"

            assessment: ManualReconciliationAssessment
            detail: str
            if item.classification in {
                "journal_history_incomplete",
                "active_pointer_missing",
                "active_pointer_mismatch",
                "candidate_record_missing",
                "candidate_identity_not_committed",
                "journal_route_evidence_incomplete",
            }:
                assessment = "durable_inventory_incomplete"
                detail = (
                    "Durable journal/history/active-pointer evidence is incomplete or inconsistent; "
                    "do not infer a recovery action"
                )
            elif route_readback is None or route_readback.status in {
                "unavailable", "unsupported", "not_found", "invalid_response",
            }:
                assessment = "route_readback_unavailable"
                detail = (
                    route_readback.detail if route_readback is not None
                    else route_error
                ) or "Live traffic target could not be established"
            elif route_readback.status != "verified":
                assessment = "route_readback_mismatch"
                detail = route_readback.detail or "Live selector differs from the durable Router registry"
            elif (
                previous_runtime.status != "verified"
                or candidate_runtime.status != "verified"
                or not previous_runtime.identity_match
                or not candidate_runtime.identity_match
                or previous_runtime.observed_runtime_id != journal.previous_runtime_id
                or candidate_runtime.observed_runtime_id != journal.candidate_runtime_id
            ):
                assessment = "runtime_identity_unverified"
                detail = (
                    "One or both runtime immutable identities could not be verified "
                    "against the durable replacement journal"
                )
            elif (
                previous_runtime.runtime_state != "running"
                or candidate_runtime.runtime_state != "running"
            ):
                assessment = "runtime_not_running"
                detail = "One or both immutable runtimes are not confirmed running"
            elif (
                previous_runtime.health_status != "healthy"
                or candidate_runtime.health_status != "healthy"
            ):
                assessment = "runtime_health_unverified"
                detail = "One or both immutable runtimes do not have a fresh healthy inspection"
            elif journal.phase == "traffic_switch_pending":
                if (
                    item.active_deployment_id == journal.previous_deployment_id
                    and route_readback.effective_runtime_id == journal.candidate_runtime_id
                ):
                    assessment = "switch_applied_before_journal_commit"
                    detail = (
                        "Live Router selector targets the candidate while the durable journal "
                        "and active deployment pointer still describe the previous runtime"
                    )
                elif (
                    item.active_deployment_id == journal.previous_deployment_id
                    and route_readback.effective_runtime_id == journal.previous_runtime_id
                ):
                    assessment = "switch_not_observed_before_journal_commit"
                    detail = (
                        "Live Router still targets the previous runtime; the durable switch intent "
                        "remains pending and requires an explicit human decision"
                    )
                else:
                    assessment = "route_active_pointer_mismatch"
                    detail = "Live traffic target cannot be reconciled with the pending switch intent and active pointer"
            elif journal.phase == "traffic_switched":
                if (
                    item.active_deployment_id == journal.target_deployment_id
                    and journal.effective_traffic_target == journal.candidate_runtime_id
                    and route_readback.effective_runtime_id == journal.effective_traffic_target
                ):
                    assessment = "route_matches_journal_and_active_pointer"
                    detail = "Live route, effective target, durable journal and active deployment pointer agree"
                else:
                    assessment = "route_active_pointer_mismatch"
                    detail = "Live route, durable switch target and active deployment pointer do not all agree"
            else:
                pointer_runtime_id = (
                    journal.previous_runtime_id
                    if item.active_deployment_id == journal.previous_deployment_id
                    else journal.candidate_runtime_id
                    if item.active_deployment_id == journal.target_deployment_id
                    else None
                )
                if pointer_runtime_id is not None and route_readback.effective_runtime_id == pointer_runtime_id:
                    assessment = "route_matches_active_pointer_journal_unresolved"
                    detail = (
                        "Live route matches the active deployment pointer, but the replacement journal "
                        "remains non-terminal and requires an explicit reconciliation decision"
                    )
                else:
                    assessment = "route_active_pointer_mismatch"
                    detail = "Live route does not match the durable active deployment pointer"

            results.append(
                DeploymentManualReconciliationReadbackItem(
                    operation_id=journal.operation_id,
                    provider=journal.provider,
                    project=journal.project,
                    environment=journal.environment,
                    phase=journal.phase,
                    inventory_classification=item.classification,
                    previous_deployment_id=journal.previous_deployment_id,
                    target_deployment_id=journal.target_deployment_id,
                    durable_active_deployment_id=item.active_deployment_id,
                    previous_runtime=previous_runtime,
                    candidate_runtime=candidate_runtime,
                    route_readback=route_readback,
                    assessment=assessment,
                    required_checks=item.recovery_assessment.required_checks,
                    detail=detail[:700],
                )
            )
        return tuple(results)

    def replace(
        self,
        request: DeploymentRequest,
        target: DeploymentRecord,
    ) -> DeploymentReplacementResult:
        """Replace the active scoped deployment with a prepared target record."""
        if not isinstance(request, DeploymentRequest):
            raise TypeError("request must be a DeploymentRequest")
        if not isinstance(target, DeploymentRecord):
            raise TypeError("target must be a DeploymentRecord")
        if not self._supports_replacement():
            return DeploymentReplacementResult(
                "unsupported",
                "configured provider does not implement the complete replacement capability",
            )
        if (
            target.provider != self.provider.name
            or target.project != request.project
            or target.environment != request.environment
            or target.version != request.version
            or target.status != "prepared"
        ):
            return DeploymentReplacementResult(
                "failed",
                "target must be prepared and match provider/project/environment/version",
            )
        if self.history.get(target.deployment_id) is not None:
            return DeploymentReplacementResult("failed", "target deployment already exists in host history")

        try:
            previous = self.history.active_deployment(
                provider=self.provider.name,
                environment=request.environment,
                project=request.project,
            )
        except Exception as exc:
            return DeploymentReplacementResult(
                "failed",
                f"active deployment history is unavailable: {type(exc).__name__}",
            )
        if previous is None:
            return DeploymentReplacementResult(
                "failed",
                "replacement requires an explicit active deployment pointer",
            )
        if (
            previous.provider != self.provider.name
            or previous.environment != request.environment
            or previous.project != request.project
            or previous.status != "running"
            or previous.deployment_id == target.deployment_id
        ):
            return DeploymentReplacementResult("failed", "active deployment identity is inconsistent")

        try:
            previous_health = self.provider.health_check(previous)
            if not isinstance(previous_health, HealthCheckResult):
                raise TypeError("provider returned an invalid previous health result")
            previous = self.history.update_health(previous.deployment_id, previous_health)
            if previous_health.status != "healthy":
                detail = (previous_health.detail or "").strip()
                probe = (previous_health.probe or "").strip()
                diagnostic = detail or probe
                suffix = f": {diagnostic[:700]}" if diagnostic else ""
                return DeploymentReplacementResult(
                    "failed",
                    f"active deployment is not freshly healthy ({previous_health.status}){suffix}",
                )
            previous_runtime_id = self.provider.immutable_runtime_id(previous)
            if not isinstance(previous_runtime_id, str) or not previous_runtime_id.strip():
                raise ValueError("provider returned no immutable previous runtime identity")
        except Exception as exc:
            return DeploymentReplacementResult(
                "failed",
                f"previous deployment preflight failed: {type(exc).__name__}",
            )

        operation_id = self._operation_id_factory()
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id_factory must return a non-empty string")
        now = self._clock()
        journal = ReplacementJournalRecord(
            operation_id=operation_id,
            provider=self.provider.name,
            project=request.project,
            environment=request.environment,
            target_deployment_id=target.deployment_id,
            previous_deployment_id=previous.deployment_id,
            phase="prepared",
            created_at=now,
            updated_at=now,
            previous_runtime_id=previous_runtime_id,
            detail="replacement scope reserved before provider side effects",
        )
        try:
            self.history.begin_replacement(journal)
        except Exception as exc:
            return DeploymentReplacementResult(
                "failed",
                f"replacement scope could not be reserved: {type(exc).__name__}",
                operation_id=operation_id,
            )

        try:
            prepared = self.provider.prepare_candidate(request, target, previous, operation_id)
            if not isinstance(prepared, DeploymentOperationResult) or prepared.status != "succeeded":
                return self._needs_reconciliation(
                    journal,
                    "candidate preparation did not report success",
                )

            started = self.provider.start_candidate(request, target, operation_id)
            candidate = started.record if isinstance(started, DeploymentOperationResult) else None
            if (
                not isinstance(started, DeploymentOperationResult)
                or started.status != "succeeded"
                or not isinstance(candidate, DeploymentRecord)
                or candidate.status != "running"
                or candidate.deployment_id != target.deployment_id
                or candidate.provider != self.provider.name
                or candidate.project != request.project
                or candidate.environment != request.environment
                or candidate.version != target.version
                or candidate.artifact.digest != target.artifact.digest
            ):
                start_detail = (
                    f": {started.status}: {(started.message or '')[:600]}"
                    if isinstance(started, DeploymentOperationResult)
                    else ""
                )
                return self._needs_reconciliation(
                    journal,
                    "candidate start did not return the expected running deployment identity"
                    + start_detail,
                )

            candidate_runtime_id = self.provider.immutable_runtime_id(candidate)
            if (
                not isinstance(candidate_runtime_id, str)
                or not candidate_runtime_id.strip()
                or candidate_runtime_id == previous_runtime_id
            ):
                return self._needs_reconciliation(
                    journal,
                    "candidate immutable runtime identity is missing or aliases the previous runtime",
                )
            self.history.append(candidate)
            journal = self._advance(
                journal,
                "candidate_started",
                candidate_runtime_id=candidate_runtime_id,
                detail="candidate started; immutable runtime identity persisted",
            )

            try:
                candidate_health = self.provider.verify_candidate(candidate)
                if not isinstance(candidate_health, HealthCheckResult):
                    raise TypeError("provider returned an invalid candidate health result")
                candidate = self.history.update_health(candidate.deployment_id, candidate_health)
            except Exception as exc:
                return self._abort_before_switch(
                    request, journal, candidate, previous, previous_runtime_id,
                    f"candidate health verification failed: {type(exc).__name__}",
                )
            if candidate_health.status != "healthy":
                return self._abort_before_switch(
                    request, journal, candidate, previous, previous_runtime_id,
                    f"candidate health is not healthy ({candidate_health.status})",
                )

            journal = self._advance(
                journal,
                "candidate_healthy",
                detail="candidate health verified healthy",
            )

            # Persist a durable intent before the first external route mutation.
            # A crash after this point is ambiguous and must be resolved only by
            # fresh provider/route inspection; startup never retries the switch.
            journal = self._advance(
                journal,
                "traffic_switch_pending",
                detail="traffic switch intent durably committed before provider mutation",
            )

            try:
                switch_result = self.provider.switch_traffic(candidate, previous, operation_id)
            except Exception as exc:
                switch_error = type(exc).__name__
            else:
                switch_error = (
                    "provider did not report successful traffic switch"
                    if not isinstance(switch_result, DeploymentOperationResult)
                    or switch_result.status != "succeeded"
                    else ""
                )

            try:
                effective_target = self.provider.read_traffic_target(request)
            except Exception as exc:
                return self._needs_reconciliation(
                    journal,
                    f"traffic read-back failed after switch attempt: {type(exc).__name__}",
                )

            if effective_target == previous_runtime_id:
                return self._abort_before_switch(
                    request,
                    journal,
                    candidate,
                    previous,
                    previous_runtime_id,
                    switch_error or "traffic read-back confirms previous runtime remains active",
                )
            if effective_target != candidate_runtime_id:
                return self._needs_reconciliation(
                    journal,
                    "traffic read-back is neither candidate nor previous immutable runtime",
                )

            # Read-back is authoritative even if the switch call returned an
            # ambiguous error: it proves the effective immutable route target.
            journal = self._advance(
                journal,
                "traffic_switched",
                effective_traffic_target=candidate_runtime_id,
                detail="traffic read-back verified candidate immutable runtime",
            )
            try:
                self.history.set_active_deployment(
                    provider=self.provider.name,
                    environment=request.environment,
                    project=request.project,
                    deployment_id=candidate.deployment_id,
                    expected_deployment_id=previous.deployment_id,
                )
            except Exception as exc:
                return self._needs_reconciliation(
                    journal,
                    f"active deployment CAS failed after verified traffic switch: {type(exc).__name__}",
                )

            try:
                retired = self.provider.retire_previous(previous, operation_id)
            except Exception as exc:
                return self._needs_reconciliation(
                    journal,
                    f"previous runtime retirement raised: {type(exc).__name__}",
                )
            if (
                not isinstance(retired, DeploymentOperationResult)
                or retired.status != "succeeded"
                or not isinstance(retired.record, DeploymentRecord)
                or retired.record.status != "stopped"
                or retired.record.deployment_id != previous.deployment_id
                or retired.record.provider != previous.provider
                or retired.record.project != previous.project
                or retired.record.environment != previous.environment
                or retired.record.artifact.digest != previous.artifact.digest
            ):
                retirement_detail = (
                    retired.message
                    if isinstance(retired, DeploymentOperationResult)
                    else "provider returned a malformed retirement result"
                )
                return self._needs_reconciliation(
                    journal,
                    "previous retirement lacks a verified stopped deployment record: "
                    + retirement_detail,
                )
            try:
                retired_runtime_id = self.provider.immutable_runtime_id(retired.record)
            except Exception as exc:
                return self._needs_reconciliation(
                    journal,
                    f"previous stopped runtime identity could not be read: {type(exc).__name__}",
                )
            if retired_runtime_id != previous_runtime_id:
                return self._needs_reconciliation(
                    journal,
                    "previous stopped record does not match the immutable runtime identity",
                )

            try:
                self.history.mark_stopped(previous)
                journal = self._advance(
                    journal,
                    "previous_retired",
                    detail="previous runtime inspect confirmed stopped; history committed",
                )
            except Exception as exc:
                return self._needs_reconciliation(
                    journal,
                    f"previous runtime retired but host history/journal commit failed: {type(exc).__name__}",
                )
            return DeploymentReplacementResult(
                "replaced",
                "candidate healthy; traffic read-back verified; previous runtime inspected stopped",
                operation_id,
                journal.phase,
                candidate,
            )
        except Exception as exc:
            return self._needs_reconciliation(
                journal,
                f"replacement stopped after unexpected provider/history failure: {type(exc).__name__}",
            )

    def _advance(self, journal: ReplacementJournalRecord, phase: str, **changes: str) -> ReplacementJournalRecord:
        updated = replace(journal, phase=phase, updated_at=self._clock(), **changes)
        self.history.update_replacement(updated, expected_phase=journal.phase)
        return updated

    def _needs_reconciliation(
        self, journal: ReplacementJournalRecord, detail: str
    ) -> DeploymentReplacementResult:
        current = journal
        if journal.phase != "needs_reconciliation":
            try:
                current = self._advance(journal, "needs_reconciliation", detail=detail[:1000])
            except Exception:
                # Preserve the existing journal phase and reservation if SQLite
                # itself is unavailable. Never release scope on uncertain state.
                pass
        return DeploymentReplacementResult(
            "needs_reconciliation", detail, journal.operation_id, current.phase
        )

    def _abort_before_switch(
        self,
        request: DeploymentRequest,
        journal: ReplacementJournalRecord,
        candidate: DeploymentRecord,
        previous: DeploymentRecord,
        previous_runtime_id: str,
        reason: str,
    ) -> DeploymentReplacementResult:
        try:
            route_before = self.provider.read_traffic_target(request)
        except Exception as exc:
            return self._needs_reconciliation(
                journal, f"{reason}; pre-abort route read-back failed: {type(exc).__name__}"
            )
        if route_before != previous_runtime_id:
            return self._needs_reconciliation(
                journal, f"{reason}; pre-abort route does not prove previous runtime is active"
            )
        try:
            aborted = self.provider.abort_candidate(candidate, journal.operation_id)
            route_after = self.provider.read_traffic_target(request)
        except Exception as exc:
            return self._needs_reconciliation(
                journal, f"{reason}; candidate abort/read-back failed: {type(exc).__name__}"
            )
        if (
            not isinstance(aborted, DeploymentOperationResult)
            or aborted.status != "succeeded"
            or not isinstance(aborted.record, DeploymentRecord)
            or aborted.record.status != "stopped"
            or aborted.record.deployment_id != candidate.deployment_id
            or aborted.record.provider != candidate.provider
            or aborted.record.project != candidate.project
            or aborted.record.environment != candidate.environment
            or aborted.record.artifact.digest != candidate.artifact.digest
        ):
            abort_detail = (
                aborted.message
                if isinstance(aborted, DeploymentOperationResult)
                else "provider returned a malformed abort result"
            )
            return self._needs_reconciliation(
                journal,
                f"{reason}; abort did not provide an inspected stopped candidate record: {abort_detail}",
            )
        try:
            stopped_runtime_id = self.provider.immutable_runtime_id(aborted.record)
        except Exception as exc:
            return self._needs_reconciliation(
                journal, f"{reason}; stopped candidate identity read failed: {type(exc).__name__}"
            )
        if stopped_runtime_id != journal.candidate_runtime_id:
            return self._needs_reconciliation(
                journal, f"{reason}; stopped candidate identity does not match its journal"
            )
        if route_after != previous_runtime_id:
            return self._needs_reconciliation(
                journal, f"{reason}; route changed or became unknown after candidate abort"
            )
        try:
            self.history.mark_stopped(candidate)
            terminal = self._advance(
                journal,
                "aborted",
                effective_traffic_target=previous_runtime_id,
                detail=f"{reason}; candidate inspect confirmed stopped and previous route remained active",
            )
        except Exception as exc:
            return self._needs_reconciliation(
                journal, f"{reason}; abort confirmed but history/journal commit failed: {type(exc).__name__}"
            )
        return DeploymentReplacementResult("failed", reason, journal.operation_id, terminal.phase, previous)
