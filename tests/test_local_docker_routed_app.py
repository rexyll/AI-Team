from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from runtime.deployment_provider import DeploymentArtifact
from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from runtime.local_docker_router_network import DockerRouterNetworkRecord, build_router_network_spec
from runtime.local_docker_routed_app import (
    ROUTED_APP_CONTAINER_INSPECT_FORMAT,
    ROUTED_APP_IMAGE_INSPECT_FORMAT,
    LocalDockerRoutedAppManager,
    build_routed_app_container_spec,
    verify_routed_app_inspection,
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


def ok(stdout=""):
    return DockerCommandResult(0, stdout, "")


def failed(stderr):
    return DockerCommandResult(1, "", stderr)


def scope_network():
    scope = TrafficRouterScope("docker-local", "app-manager", "test")
    network_spec = build_router_network_spec(scope)
    record = DockerRouterNetworkRecord(
        network_spec.network_name, "b" * 64,
        network_spec.scope_fingerprint, "bridge", False, False,
    )
    return record


def artifact():
    return DeploymentArtifact("docker-local", "ai-team/sample:v1", "a" * 64, "v1")


def ports():
    return (TrafficPortBinding(8080, 80), TrafficPortBinding(8443, 443))


def spec():
    return build_routed_app_container_spec(
        scope_network(), artifact(), "deploy-001", ports()
    )


def health_state(status="healthy"):
    now = datetime.now(timezone.utc)
    started = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    ended = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    return {
        "Status": "running",
        "StartedAt": started,
        "Health": {
            "Status": status,
            "Log": [{"Start": started, "End": ended, "ExitCode": 0, "Output": "ok"}],
        },
    }


def inspect_payload(app_spec, health="healthy"):
    exposed = {f"{p.container_port}/tcp": {} for p in app_spec.port_bindings}
    return {
        "Id": "c" * 64,
        "Name": "/" + app_spec.container_name,
        "Config": {
            "Image": app_spec.image_id,
            "Labels": dict(app_spec.labels),
            "ExposedPorts": exposed,
            "Volumes": None,
        },
        "State": health_state(health),
        "HostConfig": {
            "NetworkMode": app_spec.network_name,
            "Privileged": False,
            "PublishAllPorts": False,
            "PortBindings": None,
            "CapDrop": ["ALL"],
            "CapAdd": list(app_spec.capabilities),
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": [],
        "NetworkSettings": {
            "Networks": {
                app_spec.network_name: {
                    "NetworkID": app_spec.network_id,
                    "IPAddress": "172.30.0.8",
                    "GlobalIPv6Address": "",
                    "Aliases": [app_spec.container_name],
                }
            },
            "Ports": {key: None for key in exposed},
        },
    }


def inspect_result(app_spec, health="healthy"):
    return json.dumps(inspect_payload(app_spec, health))


def image_result(app_spec):
    return json.dumps({
        "Id": app_spec.image_id,
        "Config": {"Volumes": None},
    })


def manager_for(*results):
    runner = FakeRunner(*results)
    return LocalDockerRoutedAppManager(LocalDockerProvider(runner)), runner


def test_spec_uses_immutable_image_and_verified_scope_network_without_publish():
    app_spec = spec()
    argv = list(app_spec.run_argv)
    assert app_spec.image_id == "sha256:" + artifact().digest
    other = build_routed_app_container_spec(
        scope_network(), artifact(), "deploy-001-similar-prefix", ports()
    )
    assert other.container_name != app_spec.container_name
    assert argv[-1] == app_spec.image_id
    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == app_spec.network_name
    assert "--network-alias" in argv
    assert argv.count("--expose") == 2
    assert "--publish" not in argv and "-p" not in argv and "--publish-all" not in argv
    assert "host" not in argv


def test_spec_rejects_unsafe_or_duplicate_routed_port_bindings():
    with pytest.raises(ValueError):
        build_routed_app_container_spec(scope_network(), artifact(), "../bad", ports())
    with pytest.raises(ValueError):
        build_routed_app_container_spec(
            scope_network(), artifact(), "deploy-002",
            (TrafficPortBinding(8080, 80), TrafficPortBinding(8081, 80)),
        )


def test_spec_rejects_non_docker_artifact_and_invalid_immutable_digest():
    wrong_provider = DeploymentArtifact("other", "ref", "a" * 64, "v1")
    with pytest.raises(ValueError):
        build_routed_app_container_spec(scope_network(), wrong_provider, "deploy-003", ports())
    with pytest.raises(ValueError, match="digest"):
        DeploymentArtifact("docker-local", "ref", "bad", "v1")


def test_inspect_verifies_exact_network_id_ip_and_no_host_publish():
    app_spec = spec()
    verified = verify_routed_app_inspection(inspect_payload(app_spec), app_spec)
    assert verified.status == "verified"
    assert verified.target.runtime_id == "c" * 64
    assert verified.target.address == "172.30.0.8"
    assert verified.health_status == "healthy"
    assert verified.route_eligible is True


@pytest.mark.parametrize(
    "mutator,expected_status",
    [
        (lambda p: p.update({"Id": "short"}), "invalid_response"),
        (lambda p: p.update({"Name": "/wrong"}), "mismatch"),
        (lambda p: p["Config"].update({"Image": "sha256:" + "d" * 64}), "mismatch"),
        (lambda p: p["HostConfig"].update({"NetworkMode": "bridge"}), "mismatch"),
        (lambda p: p["HostConfig"].update({"Privileged": True}), "mismatch"),
        (lambda p: p["HostConfig"].update({"PublishAllPorts": True}), "mismatch"),
        (lambda p: p["HostConfig"].update({"PortBindings": {"80/tcp": [{"HostPort": "8080"}]} }), "mismatch"),
        (lambda p: p["HostConfig"].update({"CapAdd": ["SYS_ADMIN"]}), "mismatch"),
        (lambda p: p["NetworkSettings"]["Networks"][next(iter(p["NetworkSettings"]["Networks"]))].update({"NetworkID": "d" * 64}), "mismatch"),
        (lambda p: p["NetworkSettings"].update({"Networks": {}}), "mismatch"),
        (lambda p: p["NetworkSettings"]["Networks"][next(iter(p["NetworkSettings"]["Networks"]))].update({"IPAddress": "not-an-ip"}), "invalid_response"),
        (lambda p: p["Mounts"].append({"Type": "volume"}), "mismatch"),
    ],
)
def test_inspect_rejects_identity_network_and_publish_mismatches(mutator, expected_status):
    app_spec = spec()
    payload = inspect_payload(app_spec)
    mutator(payload)
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == expected_status
    assert result.target is None


def test_inspect_unhealthy_container_is_identity_verified_but_not_route_eligible():
    app_spec = spec()
    result = verify_routed_app_inspection(
        inspect_payload(app_spec, health="unhealthy"), app_spec
    )
    assert result.status == "verified"
    assert result.target is not None
    assert result.health_status == "unhealthy"
    assert result.route_eligible is False


def test_healthcheck_future_timestamp_is_not_route_eligible():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    payload["State"]["Health"]["Log"][0]["End"] = future
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "verified"
    assert result.health_status == "unknown"
    assert result.route_eligible is False


def test_direct_spec_construction_cannot_forge_labels_or_identity_name():
    from dataclasses import replace

    app_spec = spec()
    with pytest.raises(ValueError, match="labels"):
        replace(app_spec, labels=app_spec.labels[:-1])
    with pytest.raises(ValueError, match="deployment identity"):
        replace(
            app_spec,
            container_name="ai-team-app-forged",
            network_alias="ai-team-app-forged",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("CapDrop", ["NET_RAW"]),
        ("CapAdd", ["SYS_ADMIN"]),
        ("SecurityOpt", ["no-new-privileges:true", "seccomp=unconfined"]),
    ],
)
def test_inspect_rejects_extra_or_relaxed_container_security(field, value):
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["HostConfig"][field] = value
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "mismatch"
    assert result.target is None


def test_inspect_allows_image_extra_exposed_ports_when_unpublished():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["Config"]["ExposedPorts"]["9000/tcp"] = {}
    payload["NetworkSettings"]["Ports"]["9000/tcp"] = None
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "verified"
    assert result.target is not None
    assert result.route_eligible is True


def test_inspect_rejects_host_binding_for_extra_image_exposed_port():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["Config"]["ExposedPorts"]["9000/tcp"] = {}
    payload["NetworkSettings"]["Ports"]["9000/tcp"] = [{"HostIp": "0.0.0.0", "HostPort": "9000"}]
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "mismatch"
    assert result.target is None


def test_inspect_rejects_extra_networks_and_exposed_ports():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["NetworkSettings"]["Networks"]["other"] = {
        "NetworkID": "d" * 64, "IPAddress": "172.31.0.2", "Aliases": [],
    }
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "mismatch"
    payload = inspect_payload(app_spec)
    payload["Config"]["ExposedPorts"]["9000/tcp"] = {}
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "invalid_response"


def test_inspect_requires_exact_managed_scope_labels():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["Config"]["Labels"]["com.ai-team.router.routed-app.managed"] = "false"
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "mismatch"


def test_image_without_healthcheck_remains_unknown_but_identity_verified():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["State"]["Health"] = None
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.status == "verified"
    assert result.health_status == "unknown"


def test_image_health_must_be_fresh_after_container_start():
    app_spec = spec()
    payload = inspect_payload(app_spec)
    payload["State"]["Health"]["Log"][0]["End"] = payload["State"]["StartedAt"]
    result = verify_routed_app_inspection(payload, app_spec)
    assert result.health_status == "unknown"


def test_manager_creates_and_reinspects_exact_container_without_host_publish():
    app_spec = spec()
    manager, runner = manager_for(
        ok(image_result(app_spec)),
        failed(f"No such object: {app_spec.container_name}"),
        ok("container-short-id\n"),
        ok(inspect_result(app_spec)),
    )
    result = manager.ensure_app(app_spec, artifact())
    assert runner.calls[0][0][-1] == app_spec.image_id
    assert runner.calls[0][0][-1] != artifact().artifact_ref
    assert result.status == "created"
    assert result.target.runtime_id == "c" * 64
    assert result.health_status == "healthy"
    assert result.route_eligible is True
    run_args = runner.calls[2][0]
    assert run_args == list(app_spec.run_argv)
    assert "--publish" not in run_args and "-p" not in run_args
    assert runner.calls[1][0] == [
        "container", "inspect", "--format",
        ROUTED_APP_CONTAINER_INSPECT_FORMAT, app_spec.container_name,
    ]
    assert runner.calls[3][0] == runner.calls[1][0]


def test_existing_verified_container_is_reused_without_create():
    app_spec = spec()
    manager, runner = manager_for(
        ok(image_result(app_spec)),
        ok(inspect_result(app_spec)),
    )
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "existing"
    assert result.health_status == "healthy"
    assert result.route_eligible is True
    assert len(runner.calls) == 2


def test_ambiguous_create_is_resolved_only_by_exact_inspect():
    app_spec = spec()
    manager, runner = manager_for(
        ok(image_result(app_spec)),
        failed(f"No such object: {app_spec.container_name}"),
        failed("Docker command timed out"),
        ok(inspect_result(app_spec)),
    )
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "existing"
    assert "ambiguous create response" in result.detail
    assert len(runner.calls) == 4


def test_unverified_after_create_does_not_return_target_or_cleanup():
    app_spec = spec()
    wrong = inspect_payload(app_spec)
    wrong["HostConfig"]["PortBindings"] = {"80/tcp": [{"HostPort": "8080"}]}
    manager, runner = manager_for(
        ok(image_result(app_spec)),
        failed(f"No such object: {app_spec.container_name}"),
        ok("container-short-id\n"),
        ok(json.dumps(wrong)),
    )
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "mismatch"
    assert result.target is None
    assert all(args[0] not in {"stop", "rm"} for args, _, _ in runner.calls)


def test_image_id_mismatch_prevents_container_inspect_or_create():
    app_spec = spec()
    manager, runner = manager_for(ok(json.dumps({
        "Id": "sha256:" + "d" * 64,
        "Config": {"Volumes": None},
    })))
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "mismatch"
    assert len(runner.calls) == 1


def test_image_declared_volumes_are_rejected_before_container_creation():
    app_spec = spec()
    manager, runner = manager_for(ok(json.dumps({
        "Id": app_spec.image_id,
        "Config": {"Volumes": {"/data": {}}},
    })))
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "mismatch"
    assert len(runner.calls) == 1


def test_docker_daemon_unavailable_is_not_treated_as_container_missing():
    app_spec = spec()
    manager, runner = manager_for(failed("Cannot connect to the Docker daemon"))
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "unavailable"
    assert len(runner.calls) == 1


def test_malformed_image_response_fails_before_mutation():
    app_spec = spec()
    manager, runner = manager_for(ok("{broken"))
    result = manager.ensure_app(app_spec, artifact())
    assert result.status == "invalid_response"
    assert len(runner.calls) == 1

def test_docker_inspect_templates_tolerate_optional_absent_image_fields():
    assert '(json (index .Config "Volumes"))' in ROUTED_APP_IMAGE_INSPECT_FORMAT
    assert '(json (index .Config "Volumes"))' in ROUTED_APP_CONTAINER_INSPECT_FORMAT
    assert '.State.Health.Log' in ROUTED_APP_CONTAINER_INSPECT_FORMAT
    assert 'Output' not in ROUTED_APP_CONTAINER_INSPECT_FORMAT

