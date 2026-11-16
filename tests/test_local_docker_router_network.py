from __future__ import annotations

import json

import pytest

from runtime.deployment_provider import DockerCommandResult
from runtime.deployment_traffic_router import TrafficRouterScope
from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_network import (
    LocalDockerRouterNetworkManager,
    build_router_network_spec,
)


class FakeRunner:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append((list(args), cwd, timeout))
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def scope(project="motion", environment="test"):
    return TrafficRouterScope("docker-local", project, environment)


def ok(stdout="", stderr=""):
    return DockerCommandResult(0, stdout, stderr)


def failed(stderr):
    return DockerCommandResult(1, "", stderr)


def inspect_payload(spec, **overrides):
    payload = {
        "Name": spec.network_name,
        "Id": "a" * 64,
        "Driver": "bridge",
        "Scope": "local",
        "Internal": False,
        "Attachable": False,
        "Labels": {
            "com.ai-team.router.managed": "true",
            "com.ai-team.router.scope-sha256": spec.scope_fingerprint,
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


def provider(*results):
    runner = FakeRunner(*results)
    return LocalDockerProvider(runner), runner


def test_network_spec_is_stable_scope_specific_and_does_not_leak_names():
    first = build_router_network_spec(scope())
    assert first == build_router_network_spec(scope())
    assert first != build_router_network_spec(scope(project="other"))
    assert first != build_router_network_spec(scope(environment="prod"))
    assert first.network_name.startswith("ai-team-router-")
    assert "motion" not in first.network_name
    assert len(first.scope_fingerprint) == 64


def test_network_spec_requires_valid_scope_type():
    with pytest.raises(TypeError, match="TrafficRouterScope"):
        build_router_network_spec("motion/test")


def test_existing_exact_network_is_reused_without_create():
    spec = build_router_network_spec(scope())
    docker, runner = provider(ok(inspect_payload(spec)))

    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())

    assert result.status == "existing"
    assert result.record.network_id == "a" * 64
    assert runner.calls == [(
        ["network", "inspect", "--format", "{{json .}}", spec.network_name],
        None, docker.timeout,
    )]


def test_absent_network_is_created_then_reinspected():
    spec = build_router_network_spec(scope())
    docker, runner = provider(
        failed(f"Error response from daemon: network {spec.network_name} not found"),
        ok("b" * 64 + "\n"),
        ok(inspect_payload(spec)),
    )

    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())

    assert result.status == "created"
    assert result.record.network_id == "a" * 64
    assert runner.calls[1][0] == [
        "network", "create", "--driver", "bridge",
        "--label", "com.ai-team.router.managed=true",
        "--label", f"com.ai-team.router.scope-sha256={spec.scope_fingerprint}",
        spec.network_name,
    ]
    assert runner.calls[1][0][-1] == spec.network_name
    assert all("--publish" not in call[0] for call in runner.calls)


@pytest.mark.parametrize("overrides", [
    {"Driver": "overlay"},
    {"Scope": "swarm"},
    {"Internal": True},
    {"Attachable": True},
    {"Labels": {"com.ai-team.router.managed": "true"}},
])
def test_existing_network_with_wrong_identity_or_properties_is_not_reused(overrides):
    spec = build_router_network_spec(scope())
    docker, runner = provider(ok(inspect_payload(spec, **overrides)))

    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())

    assert result.status == "mismatch"
    assert result.record is None
    assert len(runner.calls) == 1


def test_daemon_unavailable_does_not_attempt_network_creation():
    docker, runner = provider(failed("Cannot connect to the Docker daemon"))
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "unavailable"
    assert runner.calls[0][0][0:2] == ["network", "inspect"]
    assert len(runner.calls) == 1


def test_docker_executable_missing_is_unavailable():
    docker, runner = provider(FileNotFoundError())
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "unavailable"
    assert len(runner.calls) == 1


def test_malformed_inspect_json_is_not_treated_as_missing_network():
    docker, runner = provider(ok("{broken"))
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "invalid_response"
    assert len(runner.calls) == 1


def test_invalid_network_identity_response_is_not_trusted():
    spec = build_router_network_spec(scope())
    docker, runner = provider(ok(inspect_payload(spec, Id="mutable-name")))
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "invalid_response"
    assert result.record is None
    assert len(runner.calls) == 1


def test_create_race_is_resolved_only_by_exact_post_create_inspection():
    spec = build_router_network_spec(scope())
    docker, runner = provider(
        failed(f"Error response from daemon: network {spec.network_name} not found"),
        failed("Error response from daemon: network with name already exists"),
        ok(inspect_payload(spec)),
    )
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "existing"
    assert result.record.network_id == "a" * 64
    assert len(runner.calls) == 3


def test_create_success_without_verifiable_network_is_not_success():
    spec = build_router_network_spec(scope())
    docker, runner = provider(
        failed(f"network {spec.network_name} not found"),
        ok("a" * 64),
        failed(f"network {spec.network_name} not found"),
    )
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "failed"
    assert result.record is None


def test_create_timeout_followed_by_unavailable_inspect_stays_unavailable():
    spec = build_router_network_spec(scope())
    docker, runner = provider(
        failed(f"network {spec.network_name} not found"),
        DockerCommandResult(1, "", "operation timed out"),
        failed("Cannot connect to the Docker daemon"),
    )
    result = LocalDockerRouterNetworkManager(docker).ensure_network(scope())
    assert result.status == "unavailable"
    assert result.record is None


def test_network_manager_requires_local_docker_provider():
    with pytest.raises(TypeError, match="LocalDockerProvider"):
        LocalDockerRouterNetworkManager(object())
