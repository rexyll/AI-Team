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
    inspection_supported: bool
    previous_runtime: DeploymentRuntimeInspection | None
    candidate_runtime: DeploymentRuntimeInspection | None
    route_readback_status: Literal["not_available"] = "not_available"
    automatic_recovery_allowed: Literal[False] = False


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

    def recovery_inventory(
        self,
        *,
        project: str | None = None,
        environment: str | None = None,
    ) -> tuple[DeploymentRecoveryInventoryItem, ...]:
        """Return a read-only inventory of unfinished host-owned replacements.

        This method is safe to call during host startup. It reads only SQLite
        journal/history/active-pointer state and never calls the provider. In
        particular, it does not infer that an unrecorded candidate was never
        started, does not resume/abort a transaction, and never releases the
        scope reservation. Provider runtime and traffic read-back must happen
        in a separate, explicitly authorized reconciliation operation.
        """
        snapshots = self.history.list_replacement_recovery_snapshots(
            provider=self.provider.name,
            project=project,
            environment=environment,
        )
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
                            "candidate_started", "candidate_healthy", "needs_reconciliation"
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

    def inspect_recovery_runtimes(
        self,
        *,
        project: str | None = None,
        environment: str | None = None,
    ) -> tuple[DeploymentRecoveryRuntimeInspectionItem, ...]:
        """Inspect recorded runtimes for unfinished operations without mutation.

        This optional external probe is deliberately separate from the
        SQLite-only startup inventory. It reads each recorded runtime by the
        provider's immutable identity when the provider exposes
        inspect_runtime(). It does not read or change traffic routing and
        cannot authorize candidate retirement or reconciliation.
        """
        snapshots = self.history.list_replacement_recovery_snapshots(
            provider=self.provider.name,
            project=project,
            environment=environment,
        )
        inspector = getattr(self.provider, "inspect_runtime", None)
        inspection_supported = callable(inspector)

        def inspect(record: DeploymentRecord | None) -> DeploymentRuntimeInspection | None:
            if record is None or not inspection_supported:
                return None
            try:
                observation = inspector(record)
            except Exception as exc:
                return DeploymentRuntimeInspection(
                    provider=self.provider.name,
                    deployment_id=record.deployment_id,
                    expected_runtime_id=record.container_id,
                    observed_runtime_id=None,
                    identity_match=False,
                    status="unavailable",
                    runtime_state="unknown",
                    health_status="unavailable",
                    checked_at=self._clock(),
                    probe="host provider inspection",
                    detail=f"Provider inspection raised {type(exc).__name__}",
                )
            if (
                not isinstance(observation, DeploymentRuntimeInspection)
                or observation.provider != self.provider.name
                or observation.deployment_id != record.deployment_id
                or observation.expected_runtime_id != record.container_id
            ):
                return DeploymentRuntimeInspection(
                    provider=self.provider.name,
                    deployment_id=record.deployment_id,
                    expected_runtime_id=record.container_id,
                    observed_runtime_id=None,
                    identity_match=False,
                    status="invalid_response",
                    runtime_state="unknown",
                    health_status="unknown",
                    checked_at=self._clock(),
                    probe="host provider inspection",
                    detail="Provider inspection did not match the requested host record",
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
                inspection_supported=inspection_supported,
                previous_runtime=inspect(snapshot.previous),
                candidate_runtime=inspect(snapshot.candidate),
            )
            for snapshot in snapshots
        )

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
                return DeploymentReplacementResult(
                    "failed",
                    f"active deployment is not freshly healthy ({previous_health.status})",
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
                return self._needs_reconciliation(
                    journal,
                    "candidate start did not return the expected running deployment identity",
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
                return self._needs_reconciliation(
                    journal,
                    "previous retirement lacks a verified stopped deployment record",
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
            return self._needs_reconciliation(
                journal, f"{reason}; abort did not provide an inspected stopped candidate record"
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
