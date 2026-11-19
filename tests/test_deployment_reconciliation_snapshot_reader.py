from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_reconciliation_contract import (
    ReconciliationEvidence,
    reconciliation_record_digest,
)
from runtime.deployment_reconciliation_snapshot_reader import (
    DeploymentHistoryReconciliationSnapshotReader,
    ReconciliationJournalChangedError,
    ReconciliationSnapshotReadError,
)
from runtime.deployment_replacement import ReplacementJournalRecord


class _Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


class _History:
    def __init__(self, *records):
        self.records = list(records)
        self.calls = []

    def get_replacement(self, operation_id):
        self.calls.append(operation_id)
        if not self.records:
            raise AssertionError("reader performed more journal reads than expected")
        return self.records.pop(0)


class _Collector:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def collect_current_evidence(self, record, operation):
        self.calls.append((record.operation_id, operation))
        return self.evidence


def _record(**overrides):
    values = dict(
        operation_id="replace-001",
        provider="docker-local",
        project="demo",
        environment="staging",
        target_deployment_id="release-new",
        previous_deployment_id="release-current",
        phase="needs_reconciliation",
        created_at="2026-11-18T09:00:00Z",
        updated_at="2026-11-18T09:10:00Z",
        candidate_runtime_id="runtime-candidate-immutable",
        previous_runtime_id="runtime-previous-immutable",
    )
    values.update(overrides)
    return ReplacementJournalRecord(**values)


def _evidence(operation):
    if operation == "abort_candidate":
        return (
            ReconciliationEvidence(
                evidence_id="ev-1",
                kind="provider_operation_inspection",
                source="docker-operation-api",
                observed_at="2026-11-18T09:59:30Z",
                digest_sha256="1" * 64,
            ),
            ReconciliationEvidence(
                evidence_id="ev-2",
                kind="candidate_absence",
                source="docker-inspect",
                observed_at="2026-11-18T09:59:30Z",
                digest_sha256="2" * 64,
                subject_runtime_id="runtime-candidate-immutable",
            ),
            ReconciliationEvidence(
                evidence_id="ev-3",
                kind="previous_runtime_inspection",
                source="docker-inspect",
                observed_at="2026-11-18T09:59:30Z",
                digest_sha256="3" * 64,
                subject_runtime_id="runtime-previous-immutable",
            ),
            ReconciliationEvidence(
                evidence_id="ev-4",
                kind="previous_route_readback",
                source="haproxy-runtime-api",
                observed_at="2026-11-18T09:59:30Z",
                digest_sha256="4" * 64,
                observed_runtime_id="runtime-previous-immutable",
            ),
        )
    return (
        ReconciliationEvidence(
            evidence_id="ev-1",
            kind="provider_operation_inspection",
            source="docker-operation-api",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="1" * 64,
        ),
        ReconciliationEvidence(
            evidence_id="ev-2",
            kind="candidate_route_readback",
            source="haproxy-runtime-api",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="2" * 64,
            observed_runtime_id="runtime-candidate-immutable",
        ),
        ReconciliationEvidence(
            evidence_id="ev-3",
            kind="candidate_health",
            source="docker-inspect",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="3" * 64,
            subject_runtime_id="runtime-candidate-immutable",
        ),
        ReconciliationEvidence(
            evidence_id="ev-4",
            kind="previous_runtime_retirement",
            source="docker-inspect",
            observed_at="2026-11-18T09:59:30Z",
            digest_sha256="4" * 64,
            subject_runtime_id="runtime-previous-immutable",
        ),
    )


def _reader(history, collector, *, clock=None):
    return DeploymentHistoryReconciliationSnapshotReader(
        history,
        collector,
        reader_id="host-deployment-history-reader-v1",
        clock=clock or _Clock(),
    )


def test_snapshot_reader_binds_operation_specific_evidence_to_one_journal_revision():
    record = _record()
    evidence = _evidence("abort_candidate")
    history = _History(record, record)
    collector = _Collector(evidence)
    reader = _reader(history, collector)

    snapshot = reader.read_current_snapshot("replace-001", "abort_candidate")

    assert snapshot.record == record
    assert snapshot.evidence == evidence
    assert snapshot.receipt.reader_id == "host-deployment-history-reader-v1"
    assert snapshot.receipt.operation_id == "replace-001"
    assert snapshot.receipt.journal_revision_before == reconciliation_record_digest(record)
    assert snapshot.receipt.journal_revision_after == reconciliation_record_digest(record)
    assert snapshot.receipt.evidence_sources == (
        "docker-inspect",
        "docker-operation-api",
        "haproxy-runtime-api",
    )
    assert snapshot.receipt.read_started_at == "2026-11-18T10:00:00Z"
    assert snapshot.receipt.read_completed_at == "2026-11-18T10:00:00Z"
    assert history.calls == ["replace-001", "replace-001"]
    assert collector.calls == [("replace-001", "abort_candidate")]



def test_snapshot_reader_reads_the_real_sqlite_replacement_journal(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "deployment-history.db")
    prepared = _record(
        phase="prepared",
        candidate_runtime_id=None,
        previous_runtime_id=None,
    )
    history.begin_replacement(prepared)
    started = replace(
        prepared,
        phase="candidate_started",
        updated_at="2026-11-18T09:11:00Z",
        candidate_runtime_id="runtime-candidate-immutable",
        previous_runtime_id="runtime-previous-immutable",
    )
    history.update_replacement(started, expected_phase="prepared")
    needs_reconciliation = replace(
        started,
        phase="needs_reconciliation",
        updated_at="2026-11-18T09:12:00Z",
    )
    history.update_replacement(
        needs_reconciliation,
        expected_phase="candidate_started",
    )

    collector = _Collector(_evidence("abort_candidate"))
    snapshot = _reader(history, collector).read_current_snapshot(
        "replace-001", "abort_candidate"
    )

    assert snapshot.record == needs_reconciliation
    assert snapshot.receipt.record_digest == reconciliation_record_digest(
        needs_reconciliation
    )
    assert history.get_replacement("replace-001") == needs_reconciliation
    assert collector.calls == [("replace-001", "abort_candidate")]


def test_snapshot_reader_passes_confirm_previous_retired_operation_to_collector():
    record = _record()
    evidence = _evidence("confirm_previous_retired")
    history = _History(record, record)
    collector = _Collector(evidence)

    snapshot = _reader(history, collector).read_current_snapshot(
        "replace-001", "confirm_previous_retired"
    )

    assert {item.kind for item in snapshot.evidence} == {
        "provider_operation_inspection",
        "candidate_route_readback",
        "candidate_health",
        "previous_runtime_retirement",
    }
    assert collector.calls == [("replace-001", "confirm_previous_retired")]


def test_snapshot_reader_fails_closed_when_journal_changes_during_collection():
    record = _record()
    changed = _record(updated_at="2026-11-18T09:11:00Z")
    history = _History(record, changed)
    collector = _Collector(_evidence("abort_candidate"))

    with pytest.raises(
        ReconciliationJournalChangedError,
        match="revision changed during evidence collection",
    ):
        _reader(history, collector).read_current_snapshot(
            "replace-001", "abort_candidate"
        )

    assert history.calls == ["replace-001", "replace-001"]
    assert collector.calls == [("replace-001", "abort_candidate")]


def test_snapshot_reader_rejects_missing_or_wrong_phase_journal_before_collection():
    collector = _Collector(_evidence("abort_candidate"))
    missing = _History(None)
    with pytest.raises(ReconciliationSnapshotReadError, match="not found"):
        _reader(missing, collector).read_current_snapshot(
            "replace-001", "abort_candidate"
        )
    assert collector.calls == []

    wrong_phase = _History(_record(phase="traffic_switched"))
    with pytest.raises(ReconciliationSnapshotReadError, match="needs_reconciliation"):
        _reader(wrong_phase, collector).read_current_snapshot(
            "replace-001", "abort_candidate"
        )
    assert collector.calls == []


def test_snapshot_reader_rejects_evidence_collector_failures_and_invalid_payloads():
    record = _record()

    class _FailingCollector:
        def collect_current_evidence(self, record, operation):
            raise OSError("provider API unavailable")

    with pytest.raises(ReconciliationSnapshotReadError, match="evidence collection failed"):
        _reader(_History(record), _FailingCollector()).read_current_snapshot(
            "replace-001", "abort_candidate"
        )

    class _InvalidCollector:
        def collect_current_evidence(self, record, operation):
            return [*_evidence(operation)]

    with pytest.raises(ReconciliationSnapshotReadError, match="invalid evidence tuple"):
        _reader(_History(record), _InvalidCollector()).read_current_snapshot(
            "replace-001", "abort_candidate"
        )


def test_snapshot_reader_rejects_invalid_operation_and_clock():
    record = _record()
    collector = _Collector(_evidence("abort_candidate"))
    reader = _reader(_History(record), collector)
    with pytest.raises(ValueError, match="unsupported reconciliation operation"):
        reader.read_current_snapshot("replace-001", "switch_traffic")

    class _NaiveClock:
        def __call__(self):
            return datetime(2026, 11, 18, 10, 0, 0)

    with pytest.raises(ReconciliationSnapshotReadError, match="timezone-aware"):
        _reader(_History(record, record), collector, clock=_NaiveClock()).read_current_snapshot(
            "replace-001", "abort_candidate"
        )
