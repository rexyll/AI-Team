from __future__ import annotations

import pytest

from runtime.deployment_provider import (
    DeploymentArtifact, DeploymentOperationResult, DeploymentRecord,
    DeploymentRequest, HealthCheckResult, is_rollback_candidate,
)


def artifact():
    return DeploymentArtifact("docker-local", "ai-team/demo:1.2.3", "a" * 64, "1.2.3")


def record(status="running", health_status="healthy"):
    return DeploymentRecord(
        deployment_id="deploy-001", provider="docker-local", environment="local",
        version="1.2.3", artifact=artifact(), status=status,
        health_status=health_status, created_at="2026-11-15T10:00:00Z",
        container_id="f" * 64,
    )


def test_request_requires_explicit_scope_and_unique_ports():
    request = DeploymentRequest("/workspace/demo", "demo", "local", "1.2.3", ("8080:80",), {"owner": "ai-team"})
    assert request.environment == "local"
    with pytest.raises(ValueError, match="non-empty"):
        DeploymentRequest("", "demo", "local", "1.2.3")
    with pytest.raises(ValueError, match="duplicates"):
        DeploymentRequest("/workspace/demo", "demo", "local", "1.2.3", ("8080:80", "8080:80"))


def test_artifact_requires_content_addressed_sha256():
    assert artifact().digest == "a" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        DeploymentArtifact("docker-local", "demo:latest", "bad", "1.0.0")


def test_deployment_record_binds_provider_to_artifact():
    assert record().artifact == artifact()
    with pytest.raises(ValueError, match="must match"):
        DeploymentRecord("id", "other", "local", "1.2.3", artifact(), "running", "healthy", "now")


def test_operation_result_preserves_unavailable_and_unsupported():
    unavailable = DeploymentOperationResult("deploy", "unavailable", "docker-local", "Docker daemon unavailable")
    unsupported = DeploymentOperationResult("deploy", "unsupported", "cloud", "No cloud provider configured")
    assert unavailable.status == "unavailable"
    assert unsupported.status == "unsupported"


def test_health_and_rollback_require_verified_healthy_running_record():
    health = HealthCheckResult("healthy", "2026-11-15T10:01:00Z", "http://127.0.0.1:8080/health")
    assert health.status == "healthy"
    assert is_rollback_candidate(record())
    assert not is_rollback_candidate(record(health_status="unknown"))
    assert not is_rollback_candidate(record(status="stopped"))
    assert not is_rollback_candidate(record(health_status="unhealthy"))


def test_result_rejects_cross_provider_record():
    with pytest.raises(ValueError, match="must match"):
        DeploymentOperationResult("deploy", "succeeded", "cloud", "deployed", record=record())
