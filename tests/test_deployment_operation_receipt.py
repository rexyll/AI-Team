from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_operation_receipt import (
    HostDeploymentOperationReceiptInspector,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope():
    return {
        "provider": "docker-local",
        "project": "demo",
        "environment": "staging",
        "operation_id": "operation-001",
    }


def _begin(history, *, action="retire_previous", request_digest=None):
    return history.begin_provider_operation(
        **_scope(),
        action=action,
        request_digest=request_digest or _digest(f"request:{action}"),
        started_at="2026-11-19T10:00:00Z",
    )


def _complete(history, *, action="retire_previous", status="succeeded", result_digest=None):
    history.complete_provider_operation(
        **_scope(),
        action=action,
        request_digest=_digest(f"request:{action}"),
        status=status,
        result_digest=result_digest or _digest(f"result:{action}:{status}"),
        completed_at="2026-11-19T10:00:01Z",
    )


def test_receipt_ledger_persists_started_and_terminal_host_call(tmp_path):
    db = tmp_path / "history.sqlite3"
    history = DeploymentHistoryStore(db)
    inspector = HostDeploymentOperationReceiptInspector(history)

    assert _begin(history) is True
    pending = inspector.inspect_operation(**_scope())
    assert pending.status == "in_progress"
    assert pending.action_receipt("retire_previous").completed_at is None
    assert pending.action_succeeded("retire_previous") is False

    _complete(history)
    terminal = HostDeploymentOperationReceiptInspector(
        DeploymentHistoryStore(db)
    ).inspect_operation(**_scope())
    assert terminal.status == "terminal"
    assert terminal.completion_basis == "host_call_return"
    assert terminal.action_succeeded("retire_previous") is True
    assert terminal.action_receipt("retire_previous").result_digest == _digest(
        "result:retire_previous:succeeded"
    )


def test_duplicate_begin_is_idempotent_and_never_resets_terminal_receipt(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.sqlite3")
    assert _begin(history) is True
    assert _begin(history) is False
    _complete(history)
    assert _begin(history) is False
    assert HostDeploymentOperationReceiptInspector(history).inspect_operation(
        **_scope()
    ).action_succeeded("retire_previous")


def test_duplicate_action_with_different_request_binding_is_rejected(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.sqlite3")
    assert _begin(history) is True
    with pytest.raises(ValueError, match="request digest"):
        _begin(history, request_digest=_digest("different request"))


def test_unknown_result_never_becomes_terminal_success(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.sqlite3")
    assert _begin(history) is True
    _complete(history, status="unknown")
    inspection = HostDeploymentOperationReceiptInspector(history).inspect_operation(
        **_scope()
    )
    assert inspection.status == "unknown"
    assert not inspection.action_succeeded("retire_previous")


def test_failed_return_is_terminal_but_not_successful(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.sqlite3")
    assert _begin(history) is True
    _complete(history, status="failed")
    inspection = HostDeploymentOperationReceiptInspector(history).inspect_operation(
        **_scope()
    )
    assert inspection.status == "terminal"
    assert inspection.action_receipt("retire_previous").status == "failed"
    assert not inspection.action_succeeded("retire_previous")


def test_missing_receipt_is_not_found_not_success(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.sqlite3")
    inspection = HostDeploymentOperationReceiptInspector(history).inspect_operation(
        **_scope()
    )
    assert inspection.status == "not_found"
    assert not inspection.action_succeeded("retire_previous")


def test_concurrent_begin_has_one_writer_and_preserves_one_receipt(tmp_path):
    history = DeploymentHistoryStore(tmp_path / "history.sqlite3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda _: _begin(history), range(16)))
    assert sum(created) == 1
    receipts = history.list_provider_operation_receipts(**_scope())
    assert len(receipts) == 1
    assert receipts[0].status == "in_progress"
