from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.deployment_provider import DeploymentOperationResult
from runtime.deployment_provider_operation_ledger import (
    DurableProviderOperationReceiptStore,
    provider_operation_request_digest,
)
from runtime.deployment_reconciliation_completion import (
    HostSynchronousOperationCompletionError,
    LocalDockerSynchronousOperationCompletionInspector,
)
from runtime.deployment_replacement import ReplacementJournalRecord


class _Clock:
    def __init__(self, value=None):
        self.value = value or datetime(2026, 11, 20, 2, 30, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


def _record(**overrides):
    values = dict(
        operation_id="replace-001",
        provider="docker-local",
        project="demo",
        environment="staging",
        target_deployment_id="release-new",
        previous_deployment_id="release-current",
        phase="needs_reconciliation",
        created_at="2026-11-20T02:00:00Z",
        updated_at="2026-11-20T02:10:00Z",
        candidate_runtime_id="b" * 64,
        previous_runtime_id="a" * 64,
    )
    values.update(overrides)
    return ReplacementJournalRecord(**values)


def _binding(record, action):
    if action == "abort_candidate":
        return {
            "candidate_deployment_id": record.target_deployment_id,
            "candidate_runtime_id": record.candidate_runtime_id,
            "previous_runtime_id": record.previous_runtime_id,
        }
    return {
        "previous_deployment_id": record.previous_deployment_id,
        "previous_runtime_id": record.previous_runtime_id,
    }


def _seed_receipt(
    path,
    record,
    action,
    *,
    state="returned",
    result_status="succeeded",
    binding=None,
    clock=None,
):
    clock = clock or _Clock()
    store = DurableProviderOperationReceiptStore(path, clock=clock)
    scope = dict(
        provider=record.provider,
        project=record.project,
        environment=record.environment,
        operation_id=record.operation_id,
        operation_name=action,
    )
    digest = provider_operation_request_digest(
        **scope,
        binding=binding if binding is not None else _binding(record, action),
    )
    store.begin_operation(**scope, request_digest_sha256=digest)
    if state == "returned":
        store.record_result(
            **scope,
            result=DeploymentOperationResult(
                operation=action,
                status=result_status,
                provider=record.provider,
                message="bounded fixture result",
            ),
        )
    elif state == "indeterminate":
        store.mark_indeterminate(**scope, failure_kind="fixture_failure")
    elif state != "started":
        raise AssertionError("unsupported fixture receipt state")
    return store, digest


def _inspector(path, *, clock=None, max_age=120):
    return LocalDockerSynchronousOperationCompletionInspector(
        path,
        clock=clock or _Clock(),
        max_evidence_age_seconds=max_age,
    )


@pytest.mark.parametrize(
    ("decision", "action"),
    [
        ("abort_candidate", "abort_candidate"),
        ("confirm_previous_retired", "retire_previous"),
    ],
)
def test_inspector_accepts_only_exact_successful_action_receipt(
    tmp_path, decision, action
):
    record = _record()
    path = tmp_path / "deployments.provider-operations.sqlite3"
    store, digest = _seed_receipt(path, record, action)

    completion = _inspector(path).inspect_completion(record, decision)

    assert completion.provider == "docker-local"
    assert completion.project == record.project
    assert completion.environment == record.environment
    assert completion.operation_id == record.operation_id
    assert completion.decision == decision
    assert completion.action == action
    assert completion.source_id == "docker-local-host-call-receipts"
    assert completion.request_digest_sha256 == digest
    assert len(completion.response_digest_sha256) == 64
    assert completion.completion_type == "host_synchronous_call_return"
    assert completion.result_status == "succeeded"
    assert store.get_operation_receipt(
        provider=record.provider,
        project=record.project,
        environment=record.environment,
        operation_id=record.operation_id,
        operation_name=action,
    ).state == "returned"


@pytest.mark.parametrize("state", ["started", "indeterminate"])
def test_inspector_rejects_non_returned_receipts(tmp_path, state):
    record = _record()
    path = tmp_path / "receipts.sqlite3"
    _seed_receipt(path, record, "abort_candidate", state=state)

    with pytest.raises(HostSynchronousOperationCompletionError, match="not terminal"):
        _inspector(path).inspect_completion(record, "abort_candidate")


def test_inspector_rejects_failed_host_method_result(tmp_path):
    record = _record()
    path = tmp_path / "receipts.sqlite3"
    _seed_receipt(
        path, record, "retire_previous", result_status="failed"
    )

    with pytest.raises(HostSynchronousOperationCompletionError, match="did not report success"):
        _inspector(path).inspect_completion(record, "confirm_previous_retired")


def test_inspector_recomputes_request_digest_from_immutable_journal_ids(tmp_path):
    record = _record()
    path = tmp_path / "receipts.sqlite3"
    wrong = _binding(record, "abort_candidate")
    wrong["candidate_runtime_id"] = "c" * 64
    _seed_receipt(path, record, "abort_candidate", binding=wrong)

    with pytest.raises(HostSynchronousOperationCompletionError, match="request digest"):
        _inspector(path).inspect_completion(record, "abort_candidate")


def test_inspector_rejects_wrong_scope_and_action(tmp_path):
    record = _record()
    path = tmp_path / "receipts.sqlite3"
    _seed_receipt(path, record, "retire_previous")

    with pytest.raises(HostSynchronousOperationCompletionError, match="receipt is missing"):
        _inspector(path).inspect_completion(record, "abort_candidate")

    wrong_project = _record(project="another-project")
    with pytest.raises(HostSynchronousOperationCompletionError, match="receipt is missing"):
        _inspector(path).inspect_completion(wrong_project, "confirm_previous_retired")


@pytest.mark.parametrize(
    ("clock_offset", "message"),
    [
        (-timedelta(minutes=10), "future-dated"),
        (timedelta(minutes=10), "stale"),
    ],
)
def test_inspector_rejects_future_or_stale_receipts(tmp_path, clock_offset, message):
    record = _record()
    path = tmp_path / "receipts.sqlite3"
    store_clock = _Clock()
    _seed_receipt(path, record, "abort_candidate", clock=store_clock)
    inspection_clock = _Clock(store_clock.value + clock_offset)

    with pytest.raises(HostSynchronousOperationCompletionError, match=message):
        _inspector(path, clock=inspection_clock, max_age=120).inspect_completion(
            record, "abort_candidate"
        )


def test_inspector_rejects_wrong_journal_phase_and_provider(tmp_path):
    path = tmp_path / "receipts.sqlite3"
    record = _record()
    _seed_receipt(path, record, "abort_candidate")

    with pytest.raises(HostSynchronousOperationCompletionError, match="needs_reconciliation"):
        _inspector(path).inspect_completion(
            _record(phase="traffic_switch_pending"), "abort_candidate"
        )

    with pytest.raises(HostSynchronousOperationCompletionError, match="restricted"):
        _inspector(path).inspect_completion(
            _record(provider="cloud-provider"), "abort_candidate"
        )


def test_inspector_does_not_create_or_mutate_a_missing_receipt_sidecar(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(HostSynchronousOperationCompletionError, match="sidecar is missing"):
        _inspector(path).inspect_completion(_record(), "abort_candidate")
    assert not path.exists()


def test_inspector_requires_immutable_runtime_ids_and_valid_decision(tmp_path):
    path = tmp_path / "receipts.sqlite3"
    record = _record(candidate_runtime_id=None)
    with pytest.raises(HostSynchronousOperationCompletionError, match="candidate immutable"):
        _inspector(path).inspect_completion(record, "abort_candidate")
    with pytest.raises(HostSynchronousOperationCompletionError, match="unsupported"):
        _inspector(path).inspect_completion(_record(), "switch_traffic")


def test_inspector_rejects_corrupt_sidecar_without_repairing_it(tmp_path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a sqlite database")
    before = path.read_bytes()

    with pytest.raises(HostSynchronousOperationCompletionError, match="could not be read"):
        _inspector(path).inspect_completion(_record(), "abort_candidate")

    assert path.read_bytes() == before
