from __future__ import annotations

import sqlite3

from dataclasses import replace
from pathlib import Path

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentOperationResult,
    DeploymentRecord,
    DeploymentRequest,
    HealthCheckResult,
)
from runtime.deployment_replacement import ReplacementJournalRecord
from runtime.deployment_replacement_manager import HostDeploymentReplacementManager
from runtime.deployment_provider_operation_ledger import DurableProviderOperationReceiptStore


def _record(deployment_id, *, status="running", health="healthy", version="1.0"):
    artifact = DeploymentArtifact(
        "test-provider",
        f"image:{deployment_id}",
        "a" * 64 if version == "1.0" else "b" * 64,
        version,
    )
    return DeploymentRecord(
        deployment_id=deployment_id,
        provider="test-provider",
        environment="staging",
        version=version,
        artifact=artifact,
        status=status,
        health_status=health,
        created_at="2026-11-15T12:00:00Z",
        project="demo",
    )


def _request():
    return DeploymentRequest(
        project_root="/tmp/demo",
        project="demo",
        environment="staging",
        version="2.0",
    )


class FakeReplacementProvider:
    name = "test-provider"

    def __init__(
        self,
        *,
        previous_health="healthy",
        candidate_health="healthy",
        switch_route="candidate",
        abort_succeeds=True,
        abort_returns_inspected_record=True,
        retire_succeeds=True,
        retire_returns_inspected_record=True,
    ):
        self.previous_health = previous_health
        self.candidate_health = candidate_health
        self.switch_route = switch_route
        self.abort_succeeds = abort_succeeds
        self.abort_returns_inspected_record = abort_returns_inspected_record
        self.retire_succeeds = retire_succeeds
        self.retire_returns_inspected_record = retire_returns_inspected_record
        self.route = "runtime:previous"
        self.calls = []

    def health_check(self, record):
        self.calls.append(("health_check", record.deployment_id))
        return HealthCheckResult(self.previous_health, "2026-11-15T12:01:00Z", "fake previous probe")

    def immutable_runtime_id(self, record):
        runtime_id = f"runtime:{record.deployment_id}"
        self.calls.append(("runtime_id", record.deployment_id, runtime_id))
        return runtime_id

    def prepare_candidate(self, request, target, previous, operation_id):
        self.calls.append(("prepare", target.deployment_id, operation_id))
        return DeploymentOperationResult("prepare_candidate", "succeeded", self.name, "prepared")

    def start_candidate(self, request, target, operation_id):
        self.calls.append(("start", target.deployment_id, operation_id))
        candidate = _record(
            target.deployment_id,
            status="running",
            health="unknown",
            version=target.version,
        )
        return DeploymentOperationResult(
            "start_candidate", "succeeded", self.name, "started", record=candidate
        )

    def verify_candidate(self, candidate):
        self.calls.append(("verify_candidate", candidate.deployment_id))
        return HealthCheckResult(
            self.candidate_health,
            "2026-11-15T12:02:00Z",
            "fake candidate probe",
        )

    def switch_traffic(self, candidate, previous, operation_id):
        self.calls.append(("switch_traffic", candidate.deployment_id, operation_id))
        if self.switch_route == "candidate":
            self.route = "runtime:" + candidate.deployment_id
        elif self.switch_route == "unknown":
            self.route = "runtime:unexpected"
        return DeploymentOperationResult("switch_traffic", "succeeded", self.name, "switch attempted")

    def read_traffic_target(self, request):
        self.calls.append(("read_route", self.route))
        return self.route

    def retire_previous(self, previous, operation_id):
        self.calls.append(("retire_previous", previous.deployment_id, operation_id))
        status = "succeeded" if self.retire_succeeds else "failed"
        record = replace(previous, status="stopped") if self.retire_returns_inspected_record else None
        return DeploymentOperationResult(
            "retire_previous", status, self.name, "retire result", record=record
        )

    def abort_candidate(self, candidate, operation_id):
        self.calls.append(("abort_candidate", candidate.deployment_id, operation_id))
        status = "succeeded" if self.abort_succeeds else "failed"
        record = replace(candidate, status="stopped") if self.abort_returns_inspected_record else None
        return DeploymentOperationResult(
            "abort_candidate", status, self.name, "abort result", record=record
        )


def _setup(tmp_path: Path, provider=None, operation_receipt_store=None):
    history = DeploymentHistoryStore(tmp_path / "deployments.sqlite3")
    previous = _record("previous")
    history.append(previous)
    history.set_active_deployment(
        provider=previous.provider,
        environment=previous.environment,
        project=previous.project,
        deployment_id=previous.deployment_id,
        expected_deployment_id=None,
    )
    target = _record("candidate", status="prepared", health="unknown", version="2.0")
    provider = provider or FakeReplacementProvider()
    manager = HostDeploymentReplacementManager(
        provider,
        history,
        clock=lambda: "2026-11-15T12:03:00Z",
        operation_id_factory=lambda: "operation-001",
        operation_receipt_store=operation_receipt_store,
    )
    return history, provider, manager, previous, target


def _active(history):
    return history.active_deployment(
        provider="test-provider", project="demo", environment="staging"
    )


def test_switch_intent_is_durably_committed_before_provider_route_mutation(tmp_path):
    history, provider, manager, previous, target = _setup(tmp_path)
    original_switch = provider.switch_traffic

    def inspect_pending_before_switch(candidate, old, operation_id):
        journal = history.get_replacement(operation_id)
        assert journal.phase == "traffic_switch_pending"
        assert journal.candidate_runtime_id == "runtime:candidate"
        assert journal.previous_runtime_id == "runtime:previous"
        provider.calls.append(("journal_pending_verified", operation_id))
        return original_switch(candidate, old, operation_id)

    provider.switch_traffic = inspect_pending_before_switch
    result = manager.replace(_request(), target)

    assert result.status == "replaced"
    calls = [item[0] for item in provider.calls]
    assert calls.index("journal_pending_verified") < calls.index("switch_traffic")
    journal = history.get_replacement("operation-001")
    assert journal.phase == "previous_retired"


def test_crash_after_switch_intent_is_visible_as_manual_reconciliation(tmp_path):
    history, provider, manager, previous, target = _setup(tmp_path)

    def crash_at_switch_boundary(candidate, old, operation_id):
        journal = history.get_replacement(operation_id)
        assert journal.phase == "traffic_switch_pending"
        raise KeyboardInterrupt("simulated host crash before route mutation")

    provider.switch_traffic = crash_at_switch_boundary
    with pytest.raises(KeyboardInterrupt, match="simulated host crash"):
        manager.replace(_request(), target)

    journal = history.get_replacement("operation-001")
    assert journal.phase == "traffic_switch_pending"
    inventory = manager.recovery_inventory()
    assert len(inventory) == 1
    assert inventory[0].phase == "traffic_switch_pending"
    assert inventory[0].classification == "switch_intent_requires_inspection"
    assert inventory[0].recovery_assessment.disposition == "manual_reconciliation_required"
    assert inventory[0].recovery_assessment.automatic_action == "none"
    assert provider.route == "runtime:previous"
    assert history.get("candidate").status == "running"
    assert _active(history).deployment_id == "previous"


def test_successful_replacement_requires_inspected_stopped_records(tmp_path):
    history, provider, manager, previous, target = _setup(tmp_path)

    result = manager.replace(_request(), target)

    assert result.status == "replaced"
    assert result.phase == "previous_retired"
    assert result.record.deployment_id == "candidate"
    assert _active(history).deployment_id == "candidate"
    assert history.get("previous").status == "stopped"
    assert history.get("candidate").health_status == "healthy"
    journal = history.get_replacement("operation-001")
    assert journal.phase == "previous_retired"
    assert journal.candidate_runtime_id == "runtime:candidate"
    assert journal.previous_runtime_id == "runtime:previous"
    assert journal.effective_traffic_target == "runtime:candidate"
    calls = [item[0] for item in provider.calls]
    assert calls.index("verify_candidate") < calls.index("switch_traffic")
    assert calls.index("switch_traffic") < calls.index("read_route")
    assert calls.index("read_route") < calls.index("retire_previous")


def test_unhealthy_candidate_is_aborted_only_after_old_route_and_stopped_id_are_verified(tmp_path):
    provider = FakeReplacementProvider(candidate_health="unhealthy")
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "failed"
    assert result.phase == "aborted"
    assert "abort_candidate" in [item[0] for item in provider.calls]
    assert "retire_previous" not in [item[0] for item in provider.calls]
    assert _active(history).deployment_id == "previous"
    assert history.get("candidate").status == "stopped"
    assert history.get_replacement("operation-001").phase == "aborted"


def test_unknown_route_after_switch_preserves_both_instances_and_scope_reservation(tmp_path):
    provider = FakeReplacementProvider(switch_route="unknown")
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "needs_reconciliation"
    assert result.phase == "needs_reconciliation"
    assert "retire_previous" not in [item[0] for item in provider.calls]
    assert "abort_candidate" not in [item[0] for item in provider.calls]
    assert history.get("previous").status == "running"
    assert history.get("candidate").status == "running"
    assert _active(history).deployment_id == "previous"
    assert history.get_replacement("operation-001").phase == "needs_reconciliation"
    item = manager.recovery_inventory()[0]
    assert item.classification == "reconciliation_required"
    assert item.recovery_assessment.disposition == "manual_reconciliation_required"
    assert item.recovery_assessment.automatic_action == "none"
    existing = history.get_replacement("operation-001")
    with pytest.raises(ValueError, match="scope is reserved"):
        history.begin_replacement(
            ReplacementJournalRecord(
                **{
                    **existing.__dict__,
                    "operation_id": "operation-002",
                    "target_deployment_id": "another-target",
                    "phase": "prepared",
                }
            )
        )


def test_route_still_old_after_switch_attempt_aborts_candidate_without_retiring_old(tmp_path):
    provider = FakeReplacementProvider(switch_route="previous")
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "failed"
    assert result.phase == "aborted"
    assert _active(history).deployment_id == "previous"
    assert history.get("candidate").status == "stopped"
    calls = [item[0] for item in provider.calls]
    assert "abort_candidate" in calls
    assert "retire_previous" not in calls


def test_missing_stopped_record_after_abort_keeps_transaction_reserved(tmp_path):
    provider = FakeReplacementProvider(
        candidate_health="unhealthy",
        abort_returns_inspected_record=False,
    )
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "needs_reconciliation"
    assert history.get("candidate").status == "running"
    assert history.get_replacement("operation-001").phase == "needs_reconciliation"


def test_failed_or_unverified_retirement_never_rolls_route_back_or_stops_candidate(tmp_path):
    provider = FakeReplacementProvider(retire_succeeds=False)
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "needs_reconciliation"
    assert "abort_candidate" not in [item[0] for item in provider.calls]
    assert _active(history).deployment_id == "candidate"
    assert history.get("previous").status == "running"
    assert history.get("candidate").status == "running"


def test_successful_retirement_without_stopped_inspection_record_is_not_accepted(tmp_path):
    provider = FakeReplacementProvider(retire_returns_inspected_record=False)
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "needs_reconciliation"
    assert history.get("previous").status == "running"
    assert history.get("candidate").status == "running"
    assert _active(history).deployment_id == "candidate"


def test_unhealthy_previous_blocks_before_candidate_operations_and_without_journal(tmp_path):
    provider = FakeReplacementProvider(previous_health="unknown")
    history, provider, manager, previous, target = _setup(tmp_path, provider)

    result = manager.replace(_request(), target)

    assert result.status == "failed"
    assert "fake previous probe" in result.message
    assert "prepare" not in [item[0] for item in provider.calls]
    assert "start" not in [item[0] for item in provider.calls]
    assert history.get_replacement("operation-001") is None
    assert _active(history).deployment_id == "previous"


def test_provider_without_full_replacement_contract_is_unsupported(tmp_path):
    class OldProvider:
        name = "test-provider"

        def health_check(self, record):
            raise AssertionError("unsupported providers must not be called")

    history, _, _, _, target = _setup(tmp_path)
    manager = HostDeploymentReplacementManager(
        OldProvider(), history, operation_id_factory=lambda: "unused"
    )

    result = manager.replace(_request(), target)

    assert result.status == "unsupported"
    assert history.list_active_replacements() == []


def _replacement_journal(previous, target, *, phase="prepared", **overrides):
    values = {
        "operation_id": "operation-recovery",
        "provider": previous.provider,
        "project": previous.project,
        "environment": previous.environment,
        "target_deployment_id": target.deployment_id,
        "previous_deployment_id": previous.deployment_id,
        "phase": phase,
        "created_at": "2026-11-15T12:03:00Z",
        "updated_at": "2026-11-15T12:03:00Z",
        "previous_runtime_id": "runtime:" + previous.deployment_id,
    }
    values.update(overrides)
    return ReplacementJournalRecord(**values)


def test_recovery_inventory_survives_store_reopen_without_provider_calls(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    journal = _replacement_journal(previous, target)
    history.begin_replacement(journal)

    reopened = DeploymentHistoryStore(tmp_path / "deployments.sqlite3")
    manager = HostDeploymentReplacementManager(provider, reopened)

    inventory = manager.recovery_inventory(project="demo", environment="staging")

    assert len(inventory) == 1
    item = inventory[0]
    assert item.operation_id == journal.operation_id
    assert item.phase == "prepared"
    assert item.classification == "prepared_candidate_not_persisted"
    assert item.recovery_assessment.disposition == "pre_switch_state_requires_inspection"
    assert item.recovery_assessment.automatic_action == "none"
    assert item.previous_record_present is True
    assert item.candidate_record_present is False
    assert item.active_deployment_id == previous.deployment_id
    assert item.external_state_verified is False
    assert item.automatic_recovery_allowed is False
    assert provider.calls == []
    assert reopened.get_replacement(journal.operation_id) == journal
    with pytest.raises(ValueError, match="scope is reserved"):
        reopened.begin_replacement(
            _replacement_journal(previous, _record("other-target", version="2.0"),
                                 operation_id="operation-next")
        )


def test_recovery_inventory_detects_candidate_identity_commit_window(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    candidate = _record(
        target.deployment_id, status="running", health="unknown", version=target.version
    )
    history.append(candidate)
    journal = _replacement_journal(previous, target)
    history.begin_replacement(journal)

    inventory = HostDeploymentReplacementManager(
        provider, DeploymentHistoryStore(tmp_path / "deployments.sqlite3")
    ).recovery_inventory()

    assert inventory[0].classification == "candidate_identity_not_committed"
    assert inventory[0].candidate_record_present is True
    assert inventory[0].active_deployment_id == previous.deployment_id
    assert provider.calls == []
    assert history.get_replacement(journal.operation_id) == journal


def test_recovery_inventory_recognizes_consistent_candidate_started_state(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    candidate = _record(
        target.deployment_id, status="running", health="unknown", version=target.version
    )
    history.append(candidate)
    prepared = _replacement_journal(previous, target)
    history.begin_replacement(prepared)
    started = replace(
        prepared,
        phase="candidate_started",
        candidate_runtime_id="runtime:candidate",
        updated_at="2026-11-15T12:04:00Z",
    )
    history.update_replacement(started, expected_phase="prepared")

    item = HostDeploymentReplacementManager(provider, history).recovery_inventory()[0]

    assert item.classification == "journal_history_consistent"
    assert item.recovery_assessment.disposition == "pre_switch_state_requires_inspection"
    assert item.phase == "candidate_started"
    assert item.active_deployment_id == previous.deployment_id
    assert item.external_state_verified is False
    assert item.automatic_recovery_allowed is False
    assert provider.calls == []


def test_recovery_inventory_requires_candidate_pointer_after_traffic_switched(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    candidate = _record(
        target.deployment_id, status="running", health="healthy", version=target.version
    )
    history.append(candidate)
    prepared = _replacement_journal(previous, target)
    history.begin_replacement(prepared)
    started = replace(
        prepared, phase="candidate_started", candidate_runtime_id="runtime:candidate",
        updated_at="2026-11-15T12:04:00Z",
    )
    history.update_replacement(started, expected_phase="prepared")
    healthy = replace(started, phase="candidate_healthy", updated_at="2026-11-15T12:05:00Z")
    history.update_replacement(healthy, expected_phase="candidate_started")
    pending = replace(
        healthy,
        phase="traffic_switch_pending",
        updated_at="2026-11-15T12:05:30Z",
    )
    history.update_replacement(pending, expected_phase="candidate_healthy")
    switched = replace(
        pending,
        phase="traffic_switched",
        effective_traffic_target="runtime:candidate",
        updated_at="2026-11-15T12:06:00Z",
    )
    history.update_replacement(switched, expected_phase="traffic_switch_pending")
    history.set_active_deployment(
        provider=previous.provider,
        environment=previous.environment,
        project=previous.project,
        deployment_id=candidate.deployment_id,
        expected_deployment_id=previous.deployment_id,
    )

    item = HostDeploymentReplacementManager(provider, history).recovery_inventory()[0]

    assert item.classification == "journal_history_consistent"
    assert item.active_deployment_id == candidate.deployment_id
    assert item.external_state_verified is False
    assert item.automatic_recovery_allowed is False
    assert provider.calls == []


def test_recovery_inventory_flags_candidate_record_missing_after_started_phase(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    prepared = _replacement_journal(previous, target)
    history.begin_replacement(prepared)
    started = replace(
        prepared,
        phase="candidate_started",
        candidate_runtime_id="runtime:candidate",
        updated_at="2026-11-15T12:04:00Z",
    )
    history.update_replacement(started, expected_phase="prepared")

    item = HostDeploymentReplacementManager(provider, history).recovery_inventory()[0]

    assert item.classification == "candidate_record_missing"
    assert item.candidate_record_present is False
    assert item.active_deployment_id == previous.deployment_id
    assert provider.calls == []


def test_recovery_inventory_recognizes_retired_previous_before_terminal_journal_commit(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    candidate = _record(
        target.deployment_id, status="running", health="healthy", version=target.version
    )
    history.append(candidate)
    prepared = _replacement_journal(previous, target)
    history.begin_replacement(prepared)
    started = replace(
        prepared,
        phase="candidate_started",
        candidate_runtime_id="runtime:candidate",
        updated_at="2026-11-15T12:04:00Z",
    )
    history.update_replacement(started, expected_phase="prepared")
    healthy = replace(started, phase="candidate_healthy", updated_at="2026-11-15T12:05:00Z")
    history.update_replacement(healthy, expected_phase="candidate_started")
    pending = replace(
        healthy,
        phase="traffic_switch_pending",
        updated_at="2026-11-15T12:05:30Z",
    )
    history.update_replacement(pending, expected_phase="candidate_healthy")
    switched = replace(
        pending,
        phase="traffic_switched",
        effective_traffic_target="runtime:candidate",
        updated_at="2026-11-15T12:06:00Z",
    )
    history.update_replacement(switched, expected_phase="traffic_switch_pending")
    history.set_active_deployment(
        provider=previous.provider,
        environment=previous.environment,
        project=previous.project,
        deployment_id=candidate.deployment_id,
        expected_deployment_id=previous.deployment_id,
    )
    history.mark_stopped(previous)

    item = HostDeploymentReplacementManager(provider, history).recovery_inventory()[0]

    assert item.classification == "previous_retired_commit_pending"
    assert item.recovery_assessment.disposition == "route_readback_required_before_retire"
    assert item.phase == "traffic_switched"
    assert item.active_deployment_id == candidate.deployment_id
    assert item.external_state_verified is False
    assert item.automatic_recovery_allowed is False
    assert history.get_replacement(prepared.operation_id).phase == "traffic_switched"
    assert provider.calls == []


def test_recovery_inventory_recognizes_aborted_candidate_before_terminal_journal_commit(tmp_path):
    history, provider, _, previous, target = _setup(tmp_path)
    candidate = _record(
        target.deployment_id, status="running", health="unhealthy", version=target.version
    )
    history.append(candidate)
    prepared = _replacement_journal(previous, target)
    history.begin_replacement(prepared)
    started = replace(
        prepared,
        phase="candidate_started",
        candidate_runtime_id="runtime:candidate",
        updated_at="2026-11-15T12:04:00Z",
    )
    history.update_replacement(started, expected_phase="prepared")
    history.mark_stopped(candidate)

    item = HostDeploymentReplacementManager(provider, history).recovery_inventory()[0]

    assert item.classification == "candidate_stopped_commit_pending"
    assert item.phase == "candidate_started"
    assert item.active_deployment_id == previous.deployment_id
    assert item.external_state_verified is False
    assert item.automatic_recovery_allowed is False
    assert item.recovery_assessment.disposition == "pre_switch_state_requires_inspection"
    assert history.get_replacement(prepared.operation_id).phase == "candidate_started"
    assert provider.calls == []


def test_recovery_inventory_reads_all_host_state_in_one_sqlite_connection(tmp_path, monkeypatch):
    history, provider, _, previous, target = _setup(tmp_path)
    journal = _replacement_journal(previous, target)
    history.begin_replacement(journal)

    original_connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr("runtime.deployment_history.sqlite3.connect", tracked_connect)
    inventory = HostDeploymentReplacementManager(provider, history).recovery_inventory()

    assert len(inventory) == 1
    assert inventory[0].classification == "prepared_candidate_not_persisted"
    assert len(connections) == 1
    assert provider.calls == []



def test_replacement_persists_host_provider_call_receipts_before_and_after_each_mutation(tmp_path):
    receipt_store = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operation-receipts.sqlite3"
    )
    history, provider, manager, previous, target = _setup(
        tmp_path, operation_receipt_store=receipt_store
    )

    result = manager.replace(_request(), target)

    assert result.status == "replaced"
    receipts = receipt_store.list_operation_receipts(
        provider="test-provider",
        project="demo",
        environment="staging",
        operation_id="operation-001",
    )
    assert [item.operation_name for item in receipts] == [
        "prepare_candidate",
        "retire_previous",
        "start_candidate",
        "switch_traffic",
    ]
    assert all(item.state == "returned" for item in receipts)
    assert all(item.provider_result_status == "succeeded" for item in receipts)
    assert all(item.response_digest_sha256 for item in receipts)
    assert all(item.request_digest_sha256 for item in receipts)
    assert history.get_replacement("operation-001").phase == "previous_retired"



def test_provider_call_exception_is_persisted_as_indeterminate(tmp_path):
    receipt_store = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operation-receipts.sqlite3"
    )
    provider = FakeReplacementProvider()

    def ambiguous_start(request, target, operation_id):
        provider.calls.append(("start_raises", target.deployment_id, operation_id))
        raise TimeoutError("provider call outcome cannot be established")

    provider.start_candidate = ambiguous_start
    history, provider, manager, previous, target = _setup(
        tmp_path, provider=provider, operation_receipt_store=receipt_store
    )

    result = manager.replace(_request(), target)

    assert result.status == "needs_reconciliation"
    receipts = receipt_store.list_operation_receipts(
        provider="test-provider",
        project="demo",
        environment="staging",
        operation_id="operation-001",
    )
    by_name = {item.operation_name: item for item in receipts}
    assert by_name["prepare_candidate"].state == "returned"
    assert by_name["start_candidate"].state == "indeterminate"
    assert by_name["start_candidate"].failure_kind == "TimeoutError"
    assert by_name["start_candidate"].provider_result_status is None
    assert "switch_traffic" not in by_name
    assert history.get_replacement("operation-001").phase == "needs_reconciliation"


def test_abort_path_also_records_provider_call_receipt(tmp_path):
    receipt_store = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operation-receipts.sqlite3"
    )
    provider = FakeReplacementProvider(candidate_health="unhealthy")
    history, provider, manager, previous, target = _setup(
        tmp_path, provider=provider, operation_receipt_store=receipt_store
    )

    result = manager.replace(_request(), target)

    assert result.status == "failed"
    receipts = receipt_store.list_operation_receipts(
        provider="test-provider",
        project="demo",
        environment="staging",
        operation_id="operation-001",
    )
    by_name = {item.operation_name: item for item in receipts}
    assert by_name["prepare_candidate"].state == "returned"
    assert by_name["start_candidate"].state == "returned"
    assert by_name["abort_candidate"].state == "returned"
    assert by_name["abort_candidate"].provider_result_status == "succeeded"
    assert history.get_replacement("operation-001").phase == "aborted"



def test_writable_host_manager_defaults_to_separate_durable_provider_receipt_store(tmp_path):
    history, provider, manager, previous, target = _setup(tmp_path)

    assert isinstance(manager.operation_receipt_store, DurableProviderOperationReceiptStore)
    assert manager.operation_receipt_store.path != history.path
    assert manager.operation_receipt_store.path.name == "deployments.provider-operations.sqlite3"

    result = manager.replace(_request(), target)

    assert result.status == "replaced"
    receipts = manager.operation_receipt_store.list_operation_receipts(
        provider="test-provider",
        project="demo",
        environment="staging",
        operation_id="operation-001",
    )
    assert [item.operation_name for item in receipts] == [
        "prepare_candidate",
        "retire_previous",
        "start_candidate",
        "switch_traffic",
    ]
    assert all(item.state == "returned" for item in receipts)
    assert all(item.provider_result_status == "succeeded" for item in receipts)


def test_read_only_host_manager_does_not_create_or_write_receipt_store(tmp_path):
    db = tmp_path / "history.sqlite3"
    DeploymentHistoryStore(db)
    read_only = DeploymentHistoryStore(db, read_only=True)
    manager = HostDeploymentReplacementManager(
        FakeReplacementProvider(),
        read_only,
        clock=lambda: "2026-11-15T12:03:00Z",
    )

    assert manager.operation_receipt_store is None
    assert not db.with_name("history.provider-operations.sqlite3").exists()
