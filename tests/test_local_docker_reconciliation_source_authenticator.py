from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.deployment_reconciliation_evidence_collector import (
    ReconciliationEvidenceCollectionError,
)
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.local_docker_reconciliation_source_authenticator import (
    LocalDockerReconciliationEvidenceSourceAuthenticator,
)


class _Runner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append((list(args), cwd, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _Clock:
    def __call__(self):
        return datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc)


def _identity(daemon_id="a" * 64):
    return f"{daemon_id}|docker-host|27.2.0|/var/lib/docker"


def _authenticator(result=None, *, expected_daemon_id="a" * 64):
    runner = _Runner(
        result or DockerCommandResult(0, _identity(expected_daemon_id), "")
    )
    provider = LocalDockerProvider(runner)
    authenticator = LocalDockerReconciliationEvidenceSourceAuthenticator(
        provider,
        expected_daemon_id=expected_daemon_id,
        source_ids={
            "runtime": "docker-local-daemon-runtime",
            "route": "docker-local-daemon-router",
        },
        clock=_Clock(),
    )
    return authenticator, runner


def _kwargs(role="runtime", **overrides):
    values = dict(
        role=role,
        source_id=(
            "docker-local-daemon-runtime"
            if role == "runtime"
            else "docker-local-daemon-router"
        ),
        provider="docker-local",
        project="demo",
        environment="staging",
        response_digest_sha256="b" * 64,
        observed_at="2026-11-19T09:59:55Z",
    )
    values.update(overrides)
    return values


@pytest.mark.parametrize("role", ["runtime", "route"])
def test_local_docker_source_authentication_pins_daemon_and_binds_response(role):
    authenticator, runner = _authenticator()

    receipt = authenticator.authenticate_source(**_kwargs(role))

    assert receipt.role == role
    assert receipt.source_id == _kwargs(role)["source_id"]
    assert receipt.provider == "docker-local"
    assert receipt.project == "demo"
    assert receipt.environment == "staging"
    assert receipt.response_digest_sha256 == "b" * 64
    assert len(receipt.endpoint_identity_digest_sha256) == 64
    assert receipt.endpoint_identity_digest_sha256 != "b" * 64
    assert receipt.authenticated_at == "2026-11-19T10:00:00Z"
    assert runner.calls == [
        (
            [
                "info",
                "--format",
                "{{.ID}}|{{.Name}}|{{.ServerVersion}}|{{.DockerRootDir}}",
            ],
            None,
            provider_timeout(runner),
        )
    ]


def provider_timeout(runner):
    # The provider uses its configured bounded Docker timeout for every query.
    assert runner.calls
    return runner.calls[0][2]


def test_daemon_id_mismatch_is_rejected_even_when_docker_info_succeeds():
    authenticator, runner = _authenticator(
        DockerCommandResult(0, _identity("c" * 64), "")
    )

    with pytest.raises(ReconciliationEvidenceCollectionError, match="pinned identity"):
        authenticator.authenticate_source(**_kwargs())

    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "result",
    [
        DockerCommandResult(1, "", "daemon unavailable"),
        DockerCommandResult(0, "not-a-daemon-identity", ""),
        DockerCommandResult(0, "a" * 64 + "|host||/var/lib/docker", ""),
        object(),
    ],
)
def test_unavailable_or_malformed_daemon_identity_fails_closed(result):
    authenticator, runner = _authenticator(result)

    with pytest.raises(ReconciliationEvidenceCollectionError):
        authenticator.authenticate_source(**_kwargs())

    assert len(runner.calls) == 1


def test_docker_runner_exception_fails_closed_without_leaking_error_text():
    authenticator, runner = _authenticator(RuntimeError("secret host details"))

    with pytest.raises(ReconciliationEvidenceCollectionError, match="raised an exception"):
        authenticator.authenticate_source(**_kwargs())

    assert len(runner.calls) == 1


def test_source_authenticator_rejects_provider_role_wrong_source_and_bad_scope():
    authenticator, runner = _authenticator()

    with pytest.raises(ReconciliationEvidenceCollectionError, match="cannot authenticate"):
        authenticator.authenticate_source(**_kwargs("provider_operation"))

    with pytest.raises(ReconciliationEvidenceCollectionError, match="source ID"):
        authenticator.authenticate_source(
            **_kwargs(source_id="untrusted-source")
        )

    with pytest.raises(ReconciliationEvidenceCollectionError, match="provider"):
        authenticator.authenticate_source(**_kwargs(provider="other-provider"))

    with pytest.raises(ReconciliationEvidenceCollectionError, match="project and environment"):
        authenticator.authenticate_source(**_kwargs(project=" "))

    with pytest.raises(ReconciliationEvidenceCollectionError, match="SHA-256"):
        authenticator.authenticate_source(
            **_kwargs(response_digest_sha256="not-a-digest")
        )

    assert runner.calls == []


def test_host_receipt_source_is_authenticated_without_docker_io(tmp_path):
    path = tmp_path / "provider-operations.sqlite3"
    path.write_bytes(b"existing sqlite bytes")
    if __import__("os").name == "posix":
        path.chmod(0o600)
    runner = _Runner(DockerCommandResult(0, _identity(), ""))
    provider = LocalDockerProvider(runner)
    authenticator = LocalDockerReconciliationEvidenceSourceAuthenticator(
        provider,
        expected_daemon_id="a" * 64,
        source_ids={
            "provider_operation": "docker-local-host-call-receipts",
            "runtime": "docker-local-daemon-runtime",
            "route": "docker-local-daemon-router",
        },
        operation_receipt_store_path=path,
        clock=_Clock(),
    )
    receipt = authenticator.authenticate_source(
        role="provider_operation",
        source_id="docker-local-host-call-receipts",
        provider="docker-local",
        project="demo",
        environment="staging",
        response_digest_sha256="b" * 64,
        observed_at="2026-11-19T09:59:55Z",
    )
    assert receipt.role == "provider_operation"
    assert receipt.source_id == "docker-local-host-call-receipts"
    assert len(receipt.endpoint_identity_digest_sha256) == 64
    assert runner.calls == []


def test_host_receipt_source_rejects_permissive_posix_file_mode(tmp_path):
    import os

    if os.name != "posix":
        pytest.skip("POSIX file mode contract")
    path = tmp_path / "provider-operations.sqlite3"
    path.write_bytes(b"existing sqlite bytes")
    path.chmod(0o644)
    authenticator = LocalDockerReconciliationEvidenceSourceAuthenticator(
        LocalDockerProvider(_Runner(DockerCommandResult(0, _identity(), ""))),
        expected_daemon_id="a" * 64,
        source_ids={
            "provider_operation": "docker-local-host-call-receipts",
            "runtime": "docker-local-daemon-runtime",
            "route": "docker-local-daemon-router",
        },
        operation_receipt_store_path=path,
        clock=_Clock(),
    )
    with pytest.raises(ReconciliationEvidenceCollectionError, match="permissions"):
        authenticator.authenticate_source(
            role="provider_operation",
            source_id="docker-local-host-call-receipts",
            provider="docker-local",
            project="demo",
            environment="staging",
            response_digest_sha256="b" * 64,
            observed_at="2026-11-19T09:59:55Z",
        )


def test_host_receipt_source_requires_matching_config_and_existing_file(tmp_path):
    path = tmp_path / "missing.sqlite3"
    provider = LocalDockerProvider(_Runner(DockerCommandResult(0, _identity(), "")))
    with pytest.raises(ValueError, match="configured together"):
        LocalDockerReconciliationEvidenceSourceAuthenticator(
            provider,
            expected_daemon_id="a" * 64,
            source_ids={
                "provider_operation": "docker-local-host-call-receipts",
                "runtime": "docker-local-daemon-runtime",
                "route": "docker-local-daemon-router",
            },
            clock=_Clock(),
        )
    authenticator = LocalDockerReconciliationEvidenceSourceAuthenticator(
        provider,
        expected_daemon_id="a" * 64,
        source_ids={
            "provider_operation": "docker-local-host-call-receipts",
            "runtime": "docker-local-daemon-runtime",
            "route": "docker-local-daemon-router",
        },
        operation_receipt_store_path=path,
        clock=_Clock(),
    )
    with pytest.raises(ReconciliationEvidenceCollectionError, match="unavailable"):
        authenticator.authenticate_source(
            role="provider_operation",
            source_id="docker-local-host-call-receipts",
            provider="docker-local",
            project="demo",
            environment="staging",
            response_digest_sha256="b" * 64,
            observed_at="2026-11-19T09:59:55Z",
        )


def test_host_receipt_source_rejects_group_or_other_writable_parent(tmp_path):
    import os

    if os.name != "posix":
        pytest.skip("POSIX directory permission contract")
    parent = tmp_path / "writable-receipt-parent"
    parent.mkdir()
    path = parent / "provider-operations.sqlite3"
    path.write_bytes(b"existing sqlite bytes")
    path.chmod(0o600)
    parent.chmod(0o777)
    authenticator = LocalDockerReconciliationEvidenceSourceAuthenticator(
        LocalDockerProvider(_Runner(DockerCommandResult(0, _identity(), ""))),
        expected_daemon_id="a" * 64,
        source_ids={
            "provider_operation": "docker-local-host-call-receipts",
            "runtime": "docker-local-daemon-runtime",
            "route": "docker-local-daemon-router",
        },
        operation_receipt_store_path=path,
        clock=_Clock(),
    )
    with pytest.raises(ReconciliationEvidenceCollectionError, match="ownership or permissions"):
        authenticator.authenticate_source(
            role="provider_operation",
            source_id="docker-local-host-call-receipts",
            provider="docker-local",
            project="demo",
            environment="staging",
            response_digest_sha256="b" * 64,
            observed_at="2026-11-19T09:59:55Z",
        )
