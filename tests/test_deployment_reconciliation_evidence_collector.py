from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from runtime.deployment_provider import DeploymentRuntimeInspection
from runtime.deployment_provider_operation_ledger import ProviderOperationInspection
from runtime.deployment_reconciliation_contract import reconciliation_evidence_digest
from runtime.deployment_reconciliation_evidence_collector import (
    DecisionSpecificReconciliationEvidenceCollector,
    ReconciliationEvidenceCollectionError,
    ReconciliationEvidenceSourceAuthentication,
)
from runtime.deployment_replacement import (
    DeploymentTrafficBackendReadback,
    DeploymentTrafficReadback,
    ReplacementJournalRecord,
)


class _Clock:
    def __init__(self, value="2026-11-19T10:00:00Z"):
        self.value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    def __call__(self):
        return self.value


class _OperationInspector:
    name = "docker-local"

    def __init__(self, *, status="succeeded", source_id="provider-operation-api"):
        self.status = status
        self.source_id = source_id
        self.calls = []
        self.inspected_at = "2026-11-19T09:59:55Z"

    def inspect_operation(self, *, project, environment, operation_id, operation_name):
        self.calls.append((project, environment, operation_id, operation_name))
        return ProviderOperationInspection(
            provider=self.name,
            project=project,
            environment=environment,
            operation_id=operation_id,
            operation_name=operation_name,
            source_id=self.source_id,
            status=self.status,
            inspected_at=self.inspected_at,
            provider_operation_id="provider-operation-immutable-001",
            response_digest_sha256="c" * 64,
        )


class _RuntimeInspector:
    name = "docker-local"

    def __init__(self, observations):
        self.observations = observations
        self.calls = []

    def inspect_runtime_identity(self, deployment_id, runtime_id):
        self.calls.append((deployment_id, runtime_id))
        return self.observations[(deployment_id, runtime_id)]


class _RouteInspector:
    name = "docker-local"

    def __init__(self, scope, readback):
        self.scope = scope
        self.readback = readback
        self.calls = []

    def inspect_reconciliation_route(self, journal):
        self.calls.append(journal.operation_id)
        return self.readback


class _SourceAuthenticator:
    def __init__(self):
        self.calls = []
        self.authenticated_at = "2026-11-19T09:59:59Z"
        self.endpoint_digests = {
            "provider_operation": "1" * 64,
            "runtime": "2" * 64,
            "route": "3" * 64,
        }
        self.fail_role = None
        self.mismatch_role = None

    def authenticate_source(
        self, *, role, source_id, provider, project, environment,
        response_digest_sha256, observed_at,
    ):
        self.calls.append((role, source_id, response_digest_sha256, observed_at))
        if role == self.fail_role:
            raise PermissionError("source authentication denied")
        if role == self.mismatch_role:
            source_id = "untrusted-source"
        return ReconciliationEvidenceSourceAuthentication(
            role=role,
            source_id=source_id,
            provider=provider,
            project=project,
            environment=environment,
            response_digest_sha256=response_digest_sha256,
            endpoint_identity_digest_sha256=self.endpoint_digests[role],
            authenticated_at=self.authenticated_at,
        )


def _record():
    return ReplacementJournalRecord(
        operation_id="replace-001",
        provider="docker-local",
        project="demo",
        environment="staging",
        target_deployment_id="release-new",
        previous_deployment_id="release-current",
        phase="needs_reconciliation",
        created_at="2026-11-19T09:00:00Z",
        updated_at="2026-11-19T09:40:00Z",
        candidate_runtime_id="a" * 64,
        previous_runtime_id="b" * 64,
    )


def _runtime(record, deployment_id, runtime_id, *, status="verified",
             state="running", health="healthy", checked_at="2026-11-19T09:59:55Z"):
    verified = status == "verified"
    return DeploymentRuntimeInspection(
        provider=record.provider,
        deployment_id=deployment_id,
        expected_runtime_id=runtime_id,
        observed_runtime_id=runtime_id if verified else None,
        identity_match=verified,
        status=status,
        runtime_state=state if verified else "unknown",
        health_status=health if verified else "unavailable",
        checked_at=checked_at,
        probe="docker inspect by immutable container ID",
        detail="",
    )


def _route(record, expected_runtime_id, *, status="verified",
           checked_at="2026-11-19T09:59:55Z"):
    router_id = "d" * 64
    active_slot = "slot_a"
    backends = (
        DeploymentTrafficBackendReadback(
            backend="be_p8080",
            slot=active_slot,
            expected_address="10.20.0.4",
            expected_port=8080,
            observed_address="10.20.0.4",
            observed_port=8080,
            operational_state=2,
            administrative_state=0,
            check_result=3,
            check_state=0x06,
            status="UP",
            current_sessions=0,
        ),
    )
    return DeploymentTrafficReadback(
        provider=record.provider,
        status=status,
        checked_at=checked_at,
        router_runtime_id=router_id,
        registry_active_slot=active_slot,
        registry_active_runtime_id=expected_runtime_id,
        live_active_slot=active_slot,
        effective_runtime_id=expected_runtime_id,
        route_generation="route-generation-42",
        detail="verified",
        backend_readbacks=backends,
    )


def _collector(
    record,
    *,
    operation=None,
    candidate=None,
    previous=None,
    route=None,
    authenticator=None,
    clock=None,
    max_age=120,
):
    operation = operation or _OperationInspector()
    runtime = _RuntimeInspector({
        (record.target_deployment_id, record.candidate_runtime_id): (
            candidate or _runtime(
                record, record.target_deployment_id, record.candidate_runtime_id,
                status="not_found",
            )
        ),
        (record.previous_deployment_id, record.previous_runtime_id): (
            previous or _runtime(
                record, record.previous_deployment_id, record.previous_runtime_id,
            )
        ),
    })
    route_inspector = _RouteInspector(
        SimpleNamespace(
            provider=record.provider,
            project=record.project,
            environment=record.environment,
        ),
        route or _route(record, record.previous_runtime_id),
    )
    authenticator = authenticator or _SourceAuthenticator()
    collector = DecisionSpecificReconciliationEvidenceCollector(
        provider_operation_inspector=operation,
        runtime_inspector=runtime,
        route_inspector=route_inspector,
        source_authenticator=authenticator,
        source_ids={
            "provider_operation": "provider-operation-api",
            "runtime": "docker-daemon",
            "route": "router-haproxy-admin",
        },
        max_evidence_age_seconds=max_age,
        clock=clock or _Clock(),
    )
    return collector, runtime, route_inspector, authenticator


def test_abort_candidate_collects_exact_positive_evidence_set_read_only():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status="not_found",
    )
    previous = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
    )
    operation = _OperationInspector()
    collector, runtime, route, auth = _collector(
        record, operation=operation, candidate=candidate, previous=previous
    )

    evidence = collector.collect_current_evidence(record, "abort_candidate")

    assert {item.kind for item in evidence} == {
        "provider_operation_inspection",
        "candidate_absence",
        "previous_runtime_inspection",
        "previous_route_readback",
    }
    by_kind = {item.kind: item for item in evidence}
    assert by_kind["candidate_absence"].subject_runtime_id == record.candidate_runtime_id
    assert by_kind["previous_runtime_inspection"].subject_runtime_id == record.previous_runtime_id
    assert by_kind["previous_route_readback"].observed_runtime_id == record.previous_runtime_id
    assert [item[0] for item in auth.calls] == [
        "provider_operation", "runtime", "runtime", "route"
    ]
    assert operation.calls == [("demo", "staging", "replace-001", "replacement")]
    assert runtime.calls == [
        (record.target_deployment_id, record.candidate_runtime_id),
        (record.previous_deployment_id, record.previous_runtime_id),
    ]
    assert route.calls == ["replace-001"]


def test_confirm_previous_retired_collects_exact_positive_evidence_set():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        state="running", health="healthy",
    )
    previous = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
        state="exited", health="unhealthy",
    )
    collector, runtime, route, auth = _collector(
        record,
        operation=_OperationInspector(),
        candidate=candidate,
        previous=previous,
        route=_route(record, record.candidate_runtime_id),
    )

    evidence = collector.collect_current_evidence(record, "confirm_previous_retired")

    assert {item.kind for item in evidence} == {
        "provider_operation_inspection",
        "candidate_route_readback",
        "candidate_health",
        "previous_runtime_retirement",
    }
    by_kind = {item.kind: item for item in evidence}
    assert by_kind["candidate_route_readback"].observed_runtime_id == record.candidate_runtime_id
    assert by_kind["candidate_health"].subject_runtime_id == record.candidate_runtime_id
    assert by_kind["previous_runtime_retirement"].subject_runtime_id == record.previous_runtime_id
    assert route.calls == ["replace-001"]


def test_repeated_reads_keep_semantic_evidence_digest_stable_across_timestamps():
    record = _record()
    operation = _OperationInspector()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status="not_found",
    )
    previous = _runtime(record, record.previous_deployment_id, record.previous_runtime_id)
    route_readback = _route(record, record.previous_runtime_id)
    collector, runtime, route, auth = _collector(
        record, operation=operation, candidate=candidate, previous=previous,
        route=route_readback,
    )
    first = collector.collect_current_evidence(record, "abort_candidate")

    operation.inspected_at = "2026-11-19T09:59:58Z"
    runtime.observations = {
        key: replace(value, checked_at="2026-11-19T09:59:58Z")
        for key, value in runtime.observations.items()
    }
    route.readback = replace(route.readback, checked_at="2026-11-19T09:59:58Z")
    auth.authenticated_at = "2026-11-19T09:59:59Z"
    second = collector.collect_current_evidence(record, "abort_candidate")

    assert reconciliation_evidence_digest(first) == reconciliation_evidence_digest(second)
    assert [item.evidence_id for item in first] == [item.evidence_id for item in second]
    assert [item.observed_at for item in first] != [item.observed_at for item in second]


def test_local_docker_unsupported_operation_inspection_blocks_before_runtime_or_route():
    from runtime.local_docker_provider import LocalDockerProvider

    record = _record()
    local = LocalDockerProvider()
    runtime = _RuntimeInspector({})
    route = _RouteInspector(
        SimpleNamespace(provider=record.provider, project=record.project,
                         environment=record.environment),
        _route(record, record.previous_runtime_id),
    )
    collector = DecisionSpecificReconciliationEvidenceCollector(
        provider_operation_inspector=local,
        runtime_inspector=runtime,
        route_inspector=route,
        source_authenticator=_SourceAuthenticator(),
        source_ids={
            "provider_operation": "docker-local-operation-inspection-capability",
            "runtime": "docker-daemon",
            "route": "router-haproxy-admin",
        },
        max_evidence_age_seconds=120,
        clock=_Clock(),
    )

    with pytest.raises(ReconciliationEvidenceCollectionError, match="not conclusive"):
        collector.collect_current_evidence(record, "abort_candidate")

    assert runtime.calls == []
    assert route.calls == []


@pytest.mark.parametrize("candidate_status", ["unavailable", "invalid_response", "verified"])
def test_abort_candidate_never_treats_non_not_found_candidate_as_absent(candidate_status):
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status=candidate_status,
        state="running",
        health="healthy",
    )
    collector, *_ = _collector(record, candidate=candidate)

    with pytest.raises(ReconciliationEvidenceCollectionError, match="authoritative not-found"):
        collector.collect_current_evidence(record, "abort_candidate")


def test_abort_candidate_requires_previous_runtime_running_and_healthy():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status="not_found",
    )
    previous = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
        health="unhealthy",
    )
    collector, *_ = _collector(record, candidate=candidate, previous=previous)

    with pytest.raises(ReconciliationEvidenceCollectionError, match="running and healthy"):
        collector.collect_current_evidence(record, "abort_candidate")


def test_abort_candidate_requires_effective_route_to_exact_previous_runtime():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status="not_found",
    )
    route = _route(record, "e" * 64)
    collector, *_ = _collector(record, candidate=candidate, route=route)

    with pytest.raises(ReconciliationEvidenceCollectionError, match="effective route"):
        collector.collect_current_evidence(record, "abort_candidate")


def test_confirm_previous_retired_requires_candidate_healthy_and_routed():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        health="unhealthy",
    )
    previous = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
        state="exited", health="unhealthy",
    )
    collector, *_ = _collector(
        record, candidate=candidate, previous=previous,
        route=_route(record, record.candidate_runtime_id),
    )

    with pytest.raises(ReconciliationEvidenceCollectionError, match="running and healthy"):
        collector.collect_current_evidence(record, "confirm_previous_retired")


def test_confirm_previous_retired_rejects_unqualified_previous_not_found():
    record = _record()
    candidate = _runtime(record, record.target_deployment_id, record.candidate_runtime_id)
    previous = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
        status="not_found",
    )
    collector, *_ = _collector(
        record, candidate=candidate, previous=previous,
        route=_route(record, record.candidate_runtime_id),
    )

    with pytest.raises(ReconciliationEvidenceCollectionError, match="exited/dead"):
        collector.collect_current_evidence(record, "confirm_previous_retired")


def test_confirm_previous_retired_requires_exact_candidate_route_target():
    record = _record()
    candidate = _runtime(record, record.target_deployment_id, record.candidate_runtime_id)
    previous = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
        state="exited", health="unhealthy",
    )
    collector, *_ = _collector(
        record, candidate=candidate, previous=previous,
        route=_route(record, record.previous_runtime_id),
    )

    with pytest.raises(ReconciliationEvidenceCollectionError, match="effective route"):
        collector.collect_current_evidence(record, "confirm_previous_retired")


def test_operation_inspection_scope_mismatch_is_rejected_before_runtime_reads():
    record = _record()

    class WrongScopeOperationInspector(_OperationInspector):
        def inspect_operation(self, **kwargs):
            result = super().inspect_operation(**kwargs)
            return replace(result, project="other-project")

    collector, runtime, route, _ = _collector(
        record, operation=WrongScopeOperationInspector()
    )
    with pytest.raises(ReconciliationEvidenceCollectionError, match="scope/source"):
        collector.collect_current_evidence(record, "abort_candidate")
    assert runtime.calls == []
    assert route.calls == []


def test_operation_failure_is_terminal_only_for_abort_not_retirement_confirmation():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status="not_found",
    )
    failed = _OperationInspector(status="failed")
    collector, *_ = _collector(record, operation=failed, candidate=candidate)
    evidence = collector.collect_current_evidence(record, "abort_candidate")
    assert any(item.kind == "provider_operation_inspection" for item in evidence)

    candidate_running = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id
    )
    previous_stopped = _runtime(
        record, record.previous_deployment_id, record.previous_runtime_id,
        state="exited", health="unhealthy",
    )
    collector, runtime, route, _ = _collector(
        record, operation=_OperationInspector(status="failed"),
        candidate=candidate_running, previous=previous_stopped,
        route=_route(record, record.candidate_runtime_id),
    )
    with pytest.raises(ReconciliationEvidenceCollectionError, match="not conclusive"):
        collector.collect_current_evidence(record, "confirm_previous_retired")


def test_authentication_failure_or_source_identity_mismatch_fails_closed():
    record = _record()
    auth = _SourceAuthenticator()
    auth.fail_role = "provider_operation"
    collector, runtime, route, _ = _collector(record, authenticator=auth)
    with pytest.raises(ReconciliationEvidenceCollectionError, match="authentication failed"):
        collector.collect_current_evidence(record, "abort_candidate")
    assert runtime.calls == []
    assert route.calls == []

    auth = _SourceAuthenticator()
    auth.mismatch_role = "runtime"
    collector, *_ = _collector(record, authenticator=auth)
    with pytest.raises(ReconciliationEvidenceCollectionError, match="does not match the exact response scope"):
        collector.collect_current_evidence(record, "abort_candidate")


@pytest.mark.parametrize("checked_at", [
    "2026-11-19T09:00:00Z",
    "2026-11-19T10:00:01Z",
])
def test_stale_or_future_source_observations_fail_closed(checked_at):
    record = _record()
    operation = _OperationInspector()
    operation.inspected_at = checked_at
    collector, runtime, route, auth = _collector(record, operation=operation)
    with pytest.raises(ReconciliationEvidenceCollectionError, match="stale|future-dated"):
        collector.collect_current_evidence(record, "abort_candidate")


def test_route_scope_mismatch_fails_before_route_readback_is_used():
    record = _record()
    candidate = _runtime(
        record, record.target_deployment_id, record.candidate_runtime_id,
        status="not_found",
    )
    scope = SimpleNamespace(
        provider=record.provider, project="another-project",
        environment=record.environment,
    )
    route = _RouteInspector(scope, _route(record, record.previous_runtime_id))
    collector, *_ = _collector(record, candidate=candidate, route=_route(record, record.previous_runtime_id))
    collector._route_inspector = route

    with pytest.raises(ReconciliationEvidenceCollectionError, match="scope"):
        collector.collect_current_evidence(record, "abort_candidate")


def test_malformed_inspector_payloads_fail_closed():
    record = _record()

    class BadRuntimeInspector(_RuntimeInspector):
        def inspect_runtime_identity(self, deployment_id, runtime_id):
            self.calls.append((deployment_id, runtime_id))
            return {"status": "not_found"}

    operation = _OperationInspector()
    bad_runtime = BadRuntimeInspector({
        (record.target_deployment_id, record.candidate_runtime_id): _runtime(
            record, record.target_deployment_id, record.candidate_runtime_id,
            status="not_found",
        ),
    })
    route = _RouteInspector(
        SimpleNamespace(provider=record.provider, project=record.project,
                         environment=record.environment),
        _route(record, record.previous_runtime_id),
    )
    collector = DecisionSpecificReconciliationEvidenceCollector(
        provider_operation_inspector=operation,
        runtime_inspector=bad_runtime,
        route_inspector=route,
        source_authenticator=_SourceAuthenticator(),
        source_ids={
            "provider_operation": "provider-operation-api",
            "runtime": "docker-daemon",
            "route": "router-haproxy-admin",
        },
        max_evidence_age_seconds=120,
        clock=_Clock(),
    )
    with pytest.raises(ReconciliationEvidenceCollectionError, match="invalid response"):
        collector.collect_current_evidence(record, "abort_candidate")
