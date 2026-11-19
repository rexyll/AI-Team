from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from runtime.deployment_provider import DeploymentOperationResult
from runtime.deployment_provider_operation_ledger import (
    DurableProviderOperationReceiptStore,
    ProviderOperationInspection,
    provider_operation_request_digest,
)


class _Clock:
    def __call__(self):
        return datetime(2026, 11, 19, 8, 0, 0, tzinfo=timezone.utc)


def _scope():
    return {
        "provider": "docker-local",
        "project": "demo",
        "environment": "staging",
        "operation_id": "replace-001",
        "operation_name": "switch_traffic",
    }


def _digest():
    return provider_operation_request_digest(
        **_scope(),
        binding={
            "candidate_runtime_id": "a" * 64,
            "previous_runtime_id": "b" * 64,
        },
    )


def _result(status="succeeded", message="provider returned sensitive marker"):
    return DeploymentOperationResult(
        operation="switch_traffic",
        status=status,
        provider="docker-local",
        message=message,
    )


def test_call_receipt_is_durable_scope_bound_and_stores_only_response_digest(tmp_path):
    path = tmp_path / "provider-operations.sqlite3"
    store = DurableProviderOperationReceiptStore(path, clock=_Clock())

    started = store.begin_operation(
        **_scope(),
        request_digest_sha256=_digest(),
    )
    assert started.state == "started"
    assert started.completed_at is None
    assert started.provider_result_status is None

    returned = store.record_result(
        **_scope(),
        result=_result(),
    )
    assert returned.state == "returned"
    assert returned.provider_result_status == "succeeded"
    assert returned.response_digest_sha256 is not None
    assert returned.started_at == returned.completed_at
    assert store.get_operation_receipt(**_scope()) == returned

    # The provider response body is represented only by a digest projection.
    raw = path.read_bytes()
    assert b"sensitive marker" not in raw
    assert b"provider returned" not in raw


def test_started_receipt_remains_indeterminate_after_crash_and_cannot_be_replayed(tmp_path):
    store = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operations.sqlite3", clock=_Clock()
    )
    started = store.begin_operation(
        **_scope(),
        request_digest_sha256=_digest(),
    )

    # Simulate process death: no result/exception callback is recorded.
    reloaded = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operations.sqlite3",
        clock=_Clock(),
        read_only=True,
    )
    observed = reloaded.get_operation_receipt(**_scope())
    assert observed == started
    assert observed.state == "started"

    with pytest.raises(ValueError, match="already has a durable receipt"):
        store.begin_operation(**_scope(), request_digest_sha256=_digest())


def test_exception_path_can_be_recorded_as_indeterminate_not_failed(tmp_path):
    store = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operations.sqlite3", clock=_Clock()
    )
    store.begin_operation(**_scope(), request_digest_sha256=_digest())

    receipt = store.mark_indeterminate(
        **_scope(),
        failure_kind="TimeoutError",
    )
    assert receipt.state == "indeterminate"
    assert receipt.completed_at is not None
    assert receipt.provider_result_status is None
    assert receipt.response_digest_sha256 is None
    assert receipt.failure_kind == "TimeoutError"


def test_wrong_provider_or_action_result_cannot_complete_a_receipt(tmp_path):
    store = DurableProviderOperationReceiptStore(
        tmp_path / "provider-operations.sqlite3", clock=_Clock()
    )
    store.begin_operation(**_scope(), request_digest_sha256=_digest())
    wrong = DeploymentOperationResult(
        operation="retire_previous",
        status="succeeded",
        provider="docker-local",
        message="wrong action",
    )

    with pytest.raises(ValueError, match="identity does not match"):
        store.record_result(**_scope(), result=wrong)
    assert store.get_operation_receipt(**_scope()).state == "started"


def test_provider_operation_inspection_requires_source_and_digest_for_positive_states():
    with pytest.raises(ValueError, match="provider identity and response digest"):
        ProviderOperationInspection(
            provider="cloud",
            project="demo",
            environment="prod",
            operation_id="op-1",
            operation_name="retire_previous",
            source_id="cloud-operation-api",
            status="succeeded",
            inspected_at="2026-11-19T08:00:00Z",
        )

    result = ProviderOperationInspection(
        provider="cloud",
        project="demo",
        environment="prod",
        operation_id="op-1",
        operation_name="retire_previous",
        source_id="cloud-operation-api",
        status="succeeded",
        inspected_at="2026-11-19T08:00:00Z",
        provider_operation_id="provider-op-92",
        response_digest_sha256="c" * 64,
    )
    assert result.status == "succeeded"
    assert result.provider_operation_id == "provider-op-92"


def test_read_only_ledger_rejects_begin(tmp_path):
    path = tmp_path / "provider-operations.sqlite3"
    DurableProviderOperationReceiptStore(path, clock=_Clock())
    reader = DurableProviderOperationReceiptStore(path, clock=_Clock(), read_only=True)

    with pytest.raises(PermissionError, match="read-only"):
        reader.begin_operation(**_scope(), request_digest_sha256=_digest())
