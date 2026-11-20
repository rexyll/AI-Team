"""Decision-specific, read-only reconciliation evidence collection.

This collector never mutates deployments, routers, journals or active pointers.
It accepts only exact immutable runtime observations, a provider-owned
operation-inspection response, and a verified Router/HAProxy read-back. Source
identity is authenticated by an explicitly injected Host authenticator; source
names alone are not treated as authentication.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Mapping, Protocol
from uuid import uuid4

from runtime.deployment_provider import DeploymentRuntimeInspection
from runtime.deployment_provider_operation_ledger import (
    DeploymentProviderOperationInspector,
    ProviderOperationInspection,
)
from runtime.deployment_reconciliation_completion import (
    HostSynchronousOperationCompletion,
    LocalDockerSynchronousOperationCompletionInspector,
)
from runtime.deployment_reconciliation_contract import (
    ReconciliationEvidence,
    ReconciliationOperation,
)
from runtime.deployment_replacement import (
    DeploymentTrafficReadback,
    ReplacementJournalRecord,
)

EvidenceSourceRole = Literal["provider_operation", "runtime", "route"]
_SOURCE_ROLES = {"provider_operation", "runtime", "route"}
_OPERATION_NAME = "replacement"
_SHA256_LENGTH = 64


class ReconciliationEvidenceCollectionError(RuntimeError):
    """A required source or decision-specific positive proof was unavailable."""


class ReconciliationEvidenceSourceAuthenticator(Protocol):
    """Trusted Host boundary for authenticating one concrete response source.

    Implementations must validate the real Docker daemon/socket, provider API
    endpoint or immutable Router/admin-socket identity. They must bind the
    returned receipt to the exact normalized response digest and project scope.
    """

    def authenticate_source(
        self,
        *,
        role: EvidenceSourceRole,
        source_id: str,
        provider: str,
        project: str,
        environment: str,
        response_digest_sha256: str,
        observed_at: str,
    ) -> "ReconciliationEvidenceSourceAuthentication": ...


@dataclass(frozen=True)
class ReconciliationEvidenceSourceAuthentication:
    """Host-authenticator assertion for one exact response and source identity."""

    role: EvidenceSourceRole
    source_id: str
    provider: str
    project: str
    environment: str
    response_digest_sha256: str
    endpoint_identity_digest_sha256: str
    authenticated_at: str

    def __post_init__(self) -> None:
        for name in ("source_id", "provider", "project", "environment"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.role not in _SOURCE_ROLES:
            raise ValueError("unsupported evidence source role")
        for name in ("response_digest_sha256", "endpoint_identity_digest_sha256"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != _SHA256_LENGTH
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        _parse_timestamp(self.authenticated_at, "authenticated_at")


class ReconciliationRuntimeInspector(Protocol):
    """Read-only immutable runtime identity inspection capability."""

    name: str

    def inspect_runtime_identity(
        self, deployment_id: str, runtime_id: str
    ) -> DeploymentRuntimeInspection: ...


class ReconciliationRouteInspector(Protocol):
    """Read-only Router/HAProxy inspection adapter scoped to one route."""

    name: str
    scope: object

    def inspect_reconciliation_route(
        self, journal: ReplacementJournalRecord
    ) -> DeploymentTrafficReadback: ...


def _parse_timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_response(value: object, timestamp_field: str) -> dict:
    payload = asdict(value)
    payload.pop(timestamp_field, None)
    return payload


class DecisionSpecificReconciliationEvidenceCollector:
    """Collect exact evidence for abort or retirement confirmation decisions.

    Required providers are injected independently so their source identities
    can be pinned and authenticated by the Host. Exactly one operation proof is
    required: a provider-native operation inspection, or (for Local Docker only)
    a separately typed Host synchronous completion witness. Both paths still
    require independent live runtime and route postconditions.
    """

    def __init__(
        self,
        *,
        provider_operation_inspector: DeploymentProviderOperationInspector | None = None,
        host_synchronous_completion_inspector: LocalDockerSynchronousOperationCompletionInspector | None = None,
        runtime_inspector: ReconciliationRuntimeInspector,
        route_inspector: ReconciliationRouteInspector,
        source_authenticator: ReconciliationEvidenceSourceAuthenticator,
        source_ids: Mapping[str, str],
        max_evidence_age_seconds: float,
        clock=None,
    ) -> None:
        if (provider_operation_inspector is None) == (
            host_synchronous_completion_inspector is None
        ):
            raise ValueError(
                "exactly one provider-native or Host-synchronous operation inspector is required"
            )
        operation_inspector = (
            provider_operation_inspector
            if provider_operation_inspector is not None
            else host_synchronous_completion_inspector
        )
        operation_method = (
            "inspect_operation"
            if provider_operation_inspector is not None
            else "inspect_completion"
        )
        for component, method, name in (
            (operation_inspector, operation_method, "operation completion inspector"),
            (runtime_inspector, "inspect_runtime_identity", "runtime inspector"),
            (route_inspector, "inspect_reconciliation_route", "route inspector"),
        ):
            if not callable(getattr(component, method, None)):
                raise TypeError(f"{name} does not expose its required read-only inspection method")
        if not callable(getattr(source_authenticator, "authenticate_source", None)):
            raise TypeError("source_authenticator must expose authenticate_source")
        if not isinstance(source_ids, Mapping) or set(source_ids) != _SOURCE_ROLES:
            raise ValueError("source_ids must define provider_operation, runtime and route")
        if any(not isinstance(v, str) or not v.strip() for v in source_ids.values()):
            raise ValueError("every configured source ID must be non-empty")
        for name, component in (
            ("operation completion inspector", operation_inspector),
            ("runtime inspector", runtime_inspector),
            ("route inspector", route_inspector),
        ):
            if not isinstance(getattr(component, "name", None), str) or not component.name.strip():
                raise TypeError(f"{name} must expose a non-empty provider name")
        if operation_inspector.name != runtime_inspector.name:
            raise ValueError("operation and runtime inspectors must name the same provider")
        if operation_inspector.name != route_inspector.name:
            raise ValueError("operation and route inspectors must name the same provider")
        if (
            isinstance(max_evidence_age_seconds, bool)
            or not isinstance(max_evidence_age_seconds, (int, float))
            or max_evidence_age_seconds <= 0
        ):
            raise ValueError("max_evidence_age_seconds must be positive")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._provider_operation_inspector = provider_operation_inspector
        self._host_synchronous_completion_inspector = host_synchronous_completion_inspector
        self._operation_inspector = operation_inspector
        self._provider_name = operation_inspector.name
        self._runtime_inspector = runtime_inspector
        self._route_inspector = route_inspector
        self._source_authenticator = source_authenticator
        self._source_ids = dict(source_ids)
        self._max_age = timedelta(seconds=float(max_evidence_age_seconds))
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ReconciliationEvidenceCollectionError(
                "Host evidence clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)

    def _require_fresh(self, timestamp: str, field: str) -> None:
        try:
            observed = _parse_timestamp(timestamp, field)
        except ValueError as exc:
            raise ReconciliationEvidenceCollectionError(str(exc)) from exc
        age = self._now() - observed
        if age < timedelta(0):
            raise ReconciliationEvidenceCollectionError(f"{field} is future-dated")
        if age > self._max_age:
            raise ReconciliationEvidenceCollectionError(f"{field} is stale")

    def _authenticate(
        self,
        *,
        role: EvidenceSourceRole,
        record: ReplacementJournalRecord,
        observed_at: str,
        response_digest: str,
    ) -> ReconciliationEvidenceSourceAuthentication:
        source_id = self._source_ids[role]
        try:
            receipt = self._source_authenticator.authenticate_source(
                role=role,
                source_id=source_id,
                provider=record.provider,
                project=record.project,
                environment=record.environment,
                response_digest_sha256=response_digest,
                observed_at=observed_at,
            )
        except Exception as exc:
            raise ReconciliationEvidenceCollectionError(
                f"{role} evidence source authentication failed"
            ) from exc
        if not isinstance(receipt, ReconciliationEvidenceSourceAuthentication):
            raise ReconciliationEvidenceCollectionError(
                f"{role} source authenticator returned an invalid receipt"
            )
        if (
            receipt.role != role
            or receipt.source_id != source_id
            or receipt.provider != record.provider
            or receipt.project != record.project
            or receipt.environment != record.environment
            or receipt.response_digest_sha256 != response_digest
        ):
            raise ReconciliationEvidenceCollectionError(
                f"{role} source authentication receipt does not match the exact response scope"
            )
        self._require_fresh(receipt.authenticated_at, f"{role} source authentication")
        try:
            observation_time = _parse_timestamp(observed_at, "evidence observation")
            authentication_time = _parse_timestamp(
                receipt.authenticated_at, "source authentication"
            )
        except ValueError as exc:
            raise ReconciliationEvidenceCollectionError(
                "source authentication/evidence timestamp is invalid"
            ) from exc
        if authentication_time < observation_time:
            raise ReconciliationEvidenceCollectionError(
                f"{role} source was authenticated before the response observation"
            )
        return receipt

    def _make_evidence(
        self,
        *,
        kind: str,
        role: EvidenceSourceRole,
        record: ReplacementJournalRecord,
        observation: object,
        timestamp_field: str,
        observed_at: str,
        subject_runtime_id: str | None = None,
        observed_runtime_id: str | None = None,
        provider_response_digest: str | None = None,
    ) -> ReconciliationEvidence:
        normalized = _normalized_response(observation, timestamp_field)
        response_digest = _canonical_digest(
            {
                "provider_response_digest": provider_response_digest,
                "normalized_response": normalized,
            }
        )
        source_auth = self._authenticate(
            role=role,
            record=record,
            observed_at=observed_at,
            response_digest=response_digest,
        )
        evidence_digest = _canonical_digest(
            {
                "kind": kind,
                "source_id": source_auth.source_id,
                "provider": record.provider,
                "project": record.project,
                "environment": record.environment,
                "endpoint_identity_digest_sha256": source_auth.endpoint_identity_digest_sha256,
                "response_digest_sha256": response_digest,
                "subject_runtime_id": subject_runtime_id,
                "observed_runtime_id": observed_runtime_id,
            }
        )
        evidence_id = f"{kind}:{evidence_digest[:24]}"
        return ReconciliationEvidence(
            evidence_id=evidence_id,
            kind=kind,
            source=source_auth.source_id,
            observed_at=observed_at,
            digest_sha256=evidence_digest,
            subject_runtime_id=subject_runtime_id,
            observed_runtime_id=observed_runtime_id,
        )

    def _validate_provider_operation(
        self,
        record: ReplacementJournalRecord,
        operation: ReconciliationOperation,
    ) -> ProviderOperationInspection:
        try:
            if self._provider_operation_inspector is None:
                raise RuntimeError("provider-native operation inspector is not configured")
            observation = self._provider_operation_inspector.inspect_operation(
                project=record.project,
                environment=record.environment,
                operation_id=record.operation_id,
                operation_name=_OPERATION_NAME,
            )
        except Exception as exc:
            raise ReconciliationEvidenceCollectionError(
                "provider operation inspection failed"
            ) from exc
        if not isinstance(observation, ProviderOperationInspection):
            raise ReconciliationEvidenceCollectionError(
                "provider operation inspector returned an invalid response"
            )
        if (
            observation.provider != record.provider
            or observation.project != record.project
            or observation.environment != record.environment
            or observation.operation_id != record.operation_id
            or observation.operation_name != _OPERATION_NAME
            or observation.source_id != self._source_ids["provider_operation"]
        ):
            raise ReconciliationEvidenceCollectionError(
                "provider operation inspection scope/source does not match the journal"
            )
        self._require_fresh(observation.inspected_at, "provider operation observation")
        allowed = (
            {"succeeded", "failed"}
            if operation == "abort_candidate"
            else {"succeeded"}
        )
        if observation.status not in allowed:
            raise ReconciliationEvidenceCollectionError(
                f"provider operation inspection is not conclusive for {operation}: {observation.status}"
            )
        if not observation.provider_operation_id or not observation.response_digest_sha256:
            raise ReconciliationEvidenceCollectionError(
                "terminal provider operation inspection lacks immutable operation identity/digest"
            )
        return observation

    def _validate_host_synchronous_completion(
        self,
        record: ReplacementJournalRecord,
        operation: ReconciliationOperation,
        snapshot_started_at: str | None,
    ) -> HostSynchronousOperationCompletion:
        inspector = self._host_synchronous_completion_inspector
        if inspector is None:
            raise ReconciliationEvidenceCollectionError(
                "Host synchronous completion inspector is not configured"
            )
        try:
            observation = inspector.inspect_completion(
                record, operation, not_after=snapshot_started_at
            )
        except Exception as exc:
            raise ReconciliationEvidenceCollectionError(
                "Host synchronous operation completion inspection failed"
            ) from exc
        if not isinstance(observation, HostSynchronousOperationCompletion):
            raise ReconciliationEvidenceCollectionError(
                "Host synchronous completion inspector returned an invalid response"
            )
        expected_action = (
            "abort_candidate" if operation == "abort_candidate" else "retire_previous"
        )
        if (
            observation.provider != record.provider
            or observation.project != record.project
            or observation.environment != record.environment
            or observation.operation_id != record.operation_id
            or observation.decision != operation
            or observation.action != expected_action
            or observation.source_id != self._source_ids["provider_operation"]
        ):
            raise ReconciliationEvidenceCollectionError(
                "Host synchronous completion scope/source does not match the journal"
            )
        self._require_fresh(
            observation.completed_at, "Host synchronous operation completion"
        )
        return observation

    @staticmethod
    def _validate_runtime_scope(
        observation: DeploymentRuntimeInspection,
        *,
        record: ReplacementJournalRecord,
        deployment_id: str,
        runtime_id: str,
    ) -> None:
        if (
            observation.provider != record.provider
            or observation.deployment_id != deployment_id
            or observation.expected_runtime_id != runtime_id
        ):
            raise ReconciliationEvidenceCollectionError(
                "runtime inspection identity/scope does not match the journal's immutable runtime ID"
            )

    def _inspect_runtime(
        self,
        record: ReplacementJournalRecord,
        *,
        deployment_id: str,
        runtime_id: str,
    ) -> DeploymentRuntimeInspection:
        try:
            observation = self._runtime_inspector.inspect_runtime_identity(
                deployment_id, runtime_id
            )
        except Exception as exc:
            raise ReconciliationEvidenceCollectionError(
                f"immutable runtime inspection failed for {deployment_id}"
            ) from exc
        if not isinstance(observation, DeploymentRuntimeInspection):
            raise ReconciliationEvidenceCollectionError(
                "runtime inspector returned an invalid response"
            )
        self._validate_runtime_scope(
            observation,
            record=record,
            deployment_id=deployment_id,
            runtime_id=runtime_id,
        )
        self._require_fresh(observation.checked_at, "runtime observation")
        return observation

    def _validate_route_scope(self, record: ReplacementJournalRecord) -> None:
        scope = getattr(self._route_inspector, "scope", None)
        if scope is None or any(
            getattr(scope, field, None) != getattr(record, field)
            for field in ("provider", "project", "environment")
        ):
            raise ReconciliationEvidenceCollectionError(
                "route inspector scope does not match the replacement journal"
            )

    def _inspect_route(
        self,
        record: ReplacementJournalRecord,
        *,
        expected_runtime_id: str,
    ) -> DeploymentTrafficReadback:
        self._validate_route_scope(record)
        try:
            observation = self._route_inspector.inspect_reconciliation_route(record)
        except Exception as exc:
            raise ReconciliationEvidenceCollectionError(
                "Router/HAProxy route read-back failed"
            ) from exc
        if not isinstance(observation, DeploymentTrafficReadback):
            raise ReconciliationEvidenceCollectionError(
                "route inspector returned an invalid read-back"
            )
        if observation.provider != record.provider:
            raise ReconciliationEvidenceCollectionError(
                "route read-back provider does not match the replacement journal"
            )
        self._require_fresh(observation.checked_at, "route observation")
        if (
            observation.status != "verified"
            or observation.effective_runtime_id != expected_runtime_id
            or observation.registry_active_runtime_id != expected_runtime_id
            or observation.live_active_slot != observation.registry_active_slot
            or not observation.route_generation
        ):
            raise ReconciliationEvidenceCollectionError(
                "live Router selector/effective route does not verify the required immutable runtime"
            )
        return observation

    def collect_current_evidence(
        self,
        record: ReplacementJournalRecord,
        operation: ReconciliationOperation,
        *,
        snapshot_started_at: str | None = None,
    ) -> tuple[ReconciliationEvidence, ...]:
        """Collect the exact positive evidence set for one reconciliation decision."""
        if not isinstance(record, ReplacementJournalRecord):
            raise TypeError("record must be a ReplacementJournalRecord")
        if operation not in {"abort_candidate", "confirm_previous_retired"}:
            raise ValueError("unsupported reconciliation operation")
        if record.phase != "needs_reconciliation":
            raise ReconciliationEvidenceCollectionError(
                "only needs_reconciliation journal records can be inspected"
            )
        if not record.candidate_runtime_id or not record.previous_runtime_id:
            raise ReconciliationEvidenceCollectionError(
                "journal does not contain both immutable runtime identities"
            )
        if record.provider != self._provider_name:
            raise ReconciliationEvidenceCollectionError(
                "operation inspector provider does not match the journal"
            )

        # One of two distinct completion proof types is mandatory.
        # A Host method receipt never masquerades as a provider-native operation ID.
        if self._host_synchronous_completion_inspector is not None:
            operation_observation = self._validate_host_synchronous_completion(
                record, operation, snapshot_started_at
            )
            operation_item = self._make_evidence(
                kind="host_synchronous_operation_completion",
                role="provider_operation",
                record=record,
                observation=operation_observation,
                timestamp_field="completed_at",
                observed_at=operation_observation.completed_at,
                provider_response_digest=operation_observation.response_digest_sha256,
            )
        else:
            operation_observation = self._validate_provider_operation(record, operation)
            operation_item = self._make_evidence(
                kind="provider_operation_inspection",
                role="provider_operation",
                record=record,
                observation=operation_observation,
                timestamp_field="inspected_at",
                observed_at=operation_observation.inspected_at,
                provider_response_digest=operation_observation.response_digest_sha256,
            )

        if operation == "abort_candidate":
            candidate = self._inspect_runtime(
                record,
                deployment_id=record.target_deployment_id,
                runtime_id=record.candidate_runtime_id,
            )
            if (
                candidate.status != "not_found"
                or candidate.identity_match
                or candidate.observed_runtime_id is not None
            ):
                raise ReconciliationEvidenceCollectionError(
                    "abort_candidate requires authoritative not-found for the exact candidate immutable runtime ID"
                )
            candidate_item = self._make_evidence(
                kind="candidate_absence",
                role="runtime",
                record=record,
                observation=candidate,
                timestamp_field="checked_at",
                observed_at=candidate.checked_at,
                subject_runtime_id=record.candidate_runtime_id,
            )

            previous = self._inspect_runtime(
                record,
                deployment_id=record.previous_deployment_id,
                runtime_id=record.previous_runtime_id,
            )
            if not (
                previous.status == "verified"
                and previous.identity_match
                and previous.observed_runtime_id == record.previous_runtime_id
                and previous.runtime_state == "running"
                and previous.health_status == "healthy"
            ):
                raise ReconciliationEvidenceCollectionError(
                    "abort_candidate requires the exact previous runtime to be running and healthy"
                )
            previous_item = self._make_evidence(
                kind="previous_runtime_inspection",
                role="runtime",
                record=record,
                observation=previous,
                timestamp_field="checked_at",
                observed_at=previous.checked_at,
                subject_runtime_id=record.previous_runtime_id,
            )

            route = self._inspect_route(
                record, expected_runtime_id=record.previous_runtime_id
            )
            route_item = self._make_evidence(
                kind="previous_route_readback",
                role="route",
                record=record,
                observation=route,
                timestamp_field="checked_at",
                observed_at=route.checked_at,
                observed_runtime_id=record.previous_runtime_id,
            )
            evidence = (operation_item, candidate_item, previous_item, route_item)
        else:
            route = self._inspect_route(
                record, expected_runtime_id=record.candidate_runtime_id
            )
            route_item = self._make_evidence(
                kind="candidate_route_readback",
                role="route",
                record=record,
                observation=route,
                timestamp_field="checked_at",
                observed_at=route.checked_at,
                observed_runtime_id=record.candidate_runtime_id,
            )

            candidate = self._inspect_runtime(
                record,
                deployment_id=record.target_deployment_id,
                runtime_id=record.candidate_runtime_id,
            )
            if not (
                candidate.status == "verified"
                and candidate.identity_match
                and candidate.observed_runtime_id == record.candidate_runtime_id
                and candidate.runtime_state == "running"
                and candidate.health_status == "healthy"
            ):
                raise ReconciliationEvidenceCollectionError(
                    "confirm_previous_retired requires the exact candidate runtime to be running and healthy"
                )
            candidate_item = self._make_evidence(
                kind="candidate_health",
                role="runtime",
                record=record,
                observation=candidate,
                timestamp_field="checked_at",
                observed_at=candidate.checked_at,
                subject_runtime_id=record.candidate_runtime_id,
            )

            previous = self._inspect_runtime(
                record,
                deployment_id=record.previous_deployment_id,
                runtime_id=record.previous_runtime_id,
            )
            # The Local Docker adapter's documented positive retirement state
            # is an exact immutable container still present but exited/dead.
            # An unqualified not-found is intentionally not accepted.
            if not (
                previous.status == "verified"
                and previous.identity_match
                and previous.observed_runtime_id == record.previous_runtime_id
                and previous.runtime_state in {"exited", "dead"}
            ):
                raise ReconciliationEvidenceCollectionError(
                    "confirm_previous_retired requires the exact previous runtime to be verified exited/dead"
                )
            retired_item = self._make_evidence(
                kind="previous_runtime_retirement",
                role="runtime",
                record=record,
                observation=previous,
                timestamp_field="checked_at",
                observed_at=previous.checked_at,
                subject_runtime_id=record.previous_runtime_id,
            )
            evidence = (operation_item, route_item, candidate_item, retired_item)

        self._validate_complete_evidence(operation, evidence)
        return evidence

    @staticmethod
    def _validate_complete_evidence(
        operation: ReconciliationOperation,
        evidence: tuple[ReconciliationEvidence, ...],
    ) -> None:
        required = {
            "abort_candidate": {
                "provider_operation_inspection",
                "candidate_absence",
                "previous_runtime_inspection",
                "previous_route_readback",
            },
            "confirm_previous_retired": {
                "provider_operation_inspection",
                "candidate_route_readback",
                "candidate_health",
                "previous_runtime_retirement",
            },
        }[operation]
        host_completion_required = (
            required - {"provider_operation_inspection"}
        ) | {"host_synchronous_operation_completion"}
        actual = {item.kind for item in evidence}
        if len(evidence) != 4 or actual not in (required, host_completion_required):
            raise ReconciliationEvidenceCollectionError(
                "collector did not produce the exact decision-specific evidence set"
            )
        if len({item.evidence_id for item in evidence}) != len(evidence):
            raise ReconciliationEvidenceCollectionError(
                "collector generated duplicate evidence identifiers"
            )
