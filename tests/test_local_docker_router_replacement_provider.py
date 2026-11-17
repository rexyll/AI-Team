from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import DeploymentArtifact, DeploymentOperationResult, DeploymentRecord, DeploymentRequest, HealthCheckResult
from runtime.deployment_replacement_manager import HostDeploymentReplacementManager
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_replacement_provider import LocalDockerRouterReplacementProvider


def _artifact(version, digest):
    return DeploymentArtifact("docker-local", f"sha256:{digest}", digest, version)


def _record(name, version, digest, runtime_id, status="running"):
    return DeploymentRecord(
        deployment_id=name, provider="docker-local", project="demo",
        environment="staging", version=version,
        artifact=_artifact(version, digest), status=status,
        health_status="healthy" if status == "running" else "unknown",
        created_at="2026-11-17T12:00:00Z", container_id=runtime_id,
    )


class FakeDocker:
    name = "docker-local"

    def __init__(self):
        self.stopped = set()

    def inspect_runtime(self, record):
        state = "exited" if record.container_id in self.stopped else "running"
        return SimpleNamespace(
            status="verified", observed_runtime_id=record.container_id,
            runtime_state=state, health_status="healthy" if state == "running" else "unhealthy",
            checked_at="2026-11-17T12:01:00Z", probe="fake inspect", detail="",
        )

    def _execute(self, argv):
        if argv[0] == "stop":
            self.stopped.add(argv[-1])
            return SimpleNamespace(returncode=0, stderr="", stdout=""), None
        return None, "unexpected docker command"


class FakeHost:
    def __init__(self, result):
        self.result = result
        self.provider = None
        self.history = None
    @staticmethod
    def _validate_bindings(bindings):
        return tuple(sorted(bindings, key=lambda item: item.host_port))
    def ensure_router(self, scope, bindings):
        return self.result


class FakeAppManager:
    def __init__(self, provider):
        self.provider = provider
    def ensure_app(self, spec, artifact):
        raise AssertionError("not used in this test")
    def _inspect(self, spec):
        raise AssertionError("not used in this test")


class FakeSlotManager:
    def __init__(self, provider):
        self.provider = provider
    def prepare_inactive_slot(self, **kwargs):
        raise AssertionError("not used in this test")
    def switch_active_slot(self, **kwargs):
        raise AssertionError("not used in this test")
    def drain_inactive_slot(self, **kwargs):
        raise AssertionError("not used in this test")


def test_provider_never_claims_replacement_when_router_scope_is_unavailable(tmp_path):
    docker = FakeDocker()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    host = FakeHost(SimpleNamespace(status="unavailable", detail="daemon unavailable"))
    host.provider = docker
    host.history = history
    provider = LocalDockerRouterReplacementProvider(
        docker, history, host, FakeAppManager(docker),
        FakeSlotManager(docker),
        TrafficRouterScope("docker-local", "demo", "staging"),
        (TrafficPortBinding(42699, 18080),),
    )
    result = provider.prepare_candidate(
        DeploymentRequest("/tmp/demo", "demo", "staging", "2.0"),
        _record("candidate", "2.0", "b" * 64, "b" * 64, "prepared"),
        _record("previous", "1.0", "a" * 64, "a" * 64),
        "operation-1",
    )
    assert result.status == "unavailable"
    assert "unavailable" in result.message or "daemon" in result.message


def test_immutable_stop_uses_runtime_id_and_inspect_confirmation(tmp_path):
    docker = FakeDocker()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    host = FakeHost(SimpleNamespace(status="unavailable", detail=""))
    host.provider = docker
    host.history = history
    provider = LocalDockerRouterReplacementProvider(
        docker, history, host, FakeAppManager(docker),
        FakeSlotManager(docker),
        TrafficRouterScope("docker-local", "demo", "staging"),
        (TrafficPortBinding(42699, 18080),),
    )
    previous = _record("previous", "1.0", "a" * 64, "a" * 64)
    result = provider._stop_by_immutable_id(previous)
    assert result.status == "succeeded"
    assert result.record.status == "stopped"
    assert docker.stopped == {"a" * 64}


def test_provider_rejects_cross_provider_artifact_at_constructor_boundary(tmp_path):
    docker = FakeDocker()
    history = DeploymentHistoryStore(tmp_path / "history.db")
    host = FakeHost(SimpleNamespace(status="unavailable", detail=""))
    host.provider = docker
    host.history = history
    provider = LocalDockerRouterReplacementProvider(
        docker, history, host, FakeAppManager(docker),
        FakeSlotManager(docker),
        TrafficRouterScope("docker-local", "demo", "staging"),
        (TrafficPortBinding(42699, 18080),),
    )
    bad = DeploymentArtifact("other", "image", "c" * 64, "2.0")
    with pytest.raises(ValueError):
        from runtime.local_docker_routed_app import build_routed_app_container_spec
        from runtime.local_docker_router_network import DockerRouterNetworkRecord
        build_routed_app_container_spec(
            DockerRouterNetworkRecord("ai-team-router-" + "d" * 20, "e" * 64, "f" * 64, "bridge", False, False),
            bad, "candidate", (TrafficPortBinding(42699, 18080),),
        )
