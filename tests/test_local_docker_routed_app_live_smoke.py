from __future__ import annotations

import json
import socket
import threading

from runtime.local_docker_provider import DockerCommandResult, LocalDockerProvider
from scripts.local_docker_routed_app_live_smoke import (
    cleanup_owned_app_container,
    cleanup_owned_network,
    _IMAGE_ID,
    _probe_router_tcp_route,
)


class FakeRunner:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, args, *, cwd, timeout):
        self.calls.append(list(args))
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ok(value=""):
    return DockerCommandResult(0, value, "")


def test_cleanup_app_requires_full_immutable_identity_and_scope_before_remove():
    container_id = "a" * 64
    labels = {
        "com.ai-team.router.routed-app.managed": "true",
        "com.ai-team.router.scope-sha256": "b" * 64,
        "com.ai-team.router.network-id": "c" * 64,
        "com.ai-team.router.deployment-id": "deploy-1",
        "com.ai-team.router.image-id": "sha256:" + "d" * 64,
    }
    current = {
        "Id": container_id,
        "Labels": labels,
        "Status": "running",
    }
    stopped = {**current, "Status": "exited"}
    runner = FakeRunner(
        ok(json.dumps(current)),
        ok(),
        ok(json.dumps(stopped)),
        ok(),
    )
    result = cleanup_owned_app_container(
        LocalDockerProvider(runner),
        runtime_id=container_id,
        owned=True,
        scope_fingerprint="b" * 64,
        network_id="c" * 64,
        deployment_id="deploy-1",
        image_id="sha256:" + "d" * 64,
    )
    assert result["status"] == "removed"
    assert result["container_removed"] is True
    assert runner.calls[-1] == ["container", "rm", container_id]
    assert all(container_id in args for args in runner.calls)


def test_cleanup_app_refuses_identity_or_label_mismatch():
    runner = FakeRunner(ok(json.dumps({
        "Id": "a" * 64,
        "Labels": {"com.ai-team.router.routed-app.managed": "false"},
        "Status": "running",
    })))
    result = cleanup_owned_app_container(
        LocalDockerProvider(runner),
        runtime_id="a" * 64,
        owned=True,
        scope_fingerprint="b" * 64,
        network_id="c" * 64,
        deployment_id="deploy-1",
        image_id="sha256:" + "d" * 64,
    )
    assert result["status"] == "failed"
    assert len(runner.calls) == 1


def test_cleanup_does_not_remove_preexisting_or_ambiguous_app():
    result = cleanup_owned_app_container(
        LocalDockerProvider(FakeRunner()),
        runtime_id="a" * 64,
        owned=False,
        scope_fingerprint="b" * 64,
        network_id="c" * 64,
        deployment_id="deploy-1",
        image_id="sha256:" + "d" * 64,
    )
    assert result["status"] == "preserved"


def test_cleanup_network_waits_for_confirmed_app_removal():
    runner = FakeRunner()
    result = cleanup_owned_network(
        LocalDockerProvider(runner),
        network_id="c" * 64,
        owned=True,
        scope_fingerprint="b" * 64,
        app_cleanup_status="preserved",
    )
    assert result["status"] == "preserved"
    assert runner.calls == []


def test_cleanup_network_removes_only_exact_scope_identity():
    runner = FakeRunner(ok(json.dumps({
        "Id": "c" * 64,
        "Labels": {
            "com.ai-team.router.managed": "true",
            "com.ai-team.router.scope-sha256": "b" * 64,
        },
    })), ok())
    result = cleanup_owned_network(
        LocalDockerProvider(runner),
        network_id="c" * 64,
        owned=True,
        scope_fingerprint="b" * 64,
        app_cleanup_status="removed",
    )
    assert result["status"] == "removed"
    assert runner.calls[-1] == ["network", "rm", "c" * 64]


def test_live_smoke_accepts_only_full_immutable_image_ids():
    assert _IMAGE_ID.fullmatch("sha256:" + "a" * 64)
    assert not _IMAGE_ID.fullmatch("a" * 64)
    assert not _IMAGE_ID.fullmatch("sha256:latest")


def test_cleanup_router_requires_immutable_scope_and_image_identity():
    from scripts.local_docker_routed_app_live_smoke import cleanup_owned_router_container

    router_id = "a" * 64
    labels = {
        "com.ai-team.router.managed": "true",
        "com.ai-team.router.scope-sha256": "b" * 64,
        "com.ai-team.router.network-id": "c" * 64,
        "com.ai-team.router.image-id": "sha256:" + "d" * 64,
    }
    payload = {
        "Id": router_id,
        "Config": {"Labels": labels},
        "State": {"Running": False},
    }
    runner = FakeRunner(ok(json.dumps(payload)), ok())
    result = cleanup_owned_router_container(
        LocalDockerProvider(runner),
        runtime_id=router_id,
        owned=True,
        scope_fingerprint="b" * 64,
        network_id="c" * 64,
        image_id="sha256:" + "d" * 64,
        attempted=True,
    )
    assert result["status"] == "removed"
    assert runner.calls[-1] == ["container", "rm", router_id]


def test_cleanup_network_requires_router_and_app_cleanup():
    runner = FakeRunner()
    result = cleanup_owned_network(
        LocalDockerProvider(runner),
        network_id="c" * 64,
        owned=True,
        scope_fingerprint="b" * 64,
        app_cleanup_status="removed",
        router_cleanup_status="preserved",
    )
    assert result["status"] == "preserved"
    assert runner.calls == []


def test_router_tcp_route_probe_requires_the_exact_application_marker():
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.sendall(b"ROUTED_APP_OK")
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    result = _probe_router_tcp_route(port, attempts=1, interval_seconds=0)
    thread.join(timeout=2)
    assert result["status"] == "passed"
    assert result["marker"] == "ROUTED_APP_OK"
    assert result["attempts"] == 1


def test_router_tcp_route_probe_rejects_a_different_backend_marker():
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.sendall(b"WRONG_BACKEND")
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    import pytest
    with pytest.raises(RuntimeError, match="expected app marker"):
        _probe_router_tcp_route(port, attempts=1, interval_seconds=0)
    thread.join(timeout=2)
