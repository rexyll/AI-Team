from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentRecord,
    DeploymentRequest,
    HealthCheckResult,
)
from runtime.deployment_replacement_manager import HostDeploymentReplacementManager
from runtime.deployment_traffic_router import (
    TrafficPortBinding,
    TrafficRouteTarget,
    TrafficRouterRecord,
    TrafficRouterScope,
)
from runtime.local_docker_provider import DockerCommandResult
from runtime.local_docker_router_config import HAPROXY_ACTIVE_SLOT_MAP
from runtime.local_docker_router_host import LocalDockerRouterHostManager
from runtime.local_docker_router_image import (
    DockerRouterImageIdentity,
    ROUTER_BASE_IMAGE_REF,
    ROUTER_HAPROXY_VERSION,
    ROUTER_SOCAT_PACKAGE_VERSION,
)
from runtime.local_docker_router_network import (
    DockerRouterNetworkRecord,
    build_router_network_spec,
)
from runtime.local_docker_router_state import LocalDockerRouterStateStore
from runtime.local_docker_router_container import build_router_container_spec
from runtime.local_docker_router_replacement_provider import LocalDockerRouterReplacementProvider
import runtime.local_docker_router_replacement_provider as adapter_module


SCOPE = TrafficRouterScope("docker-local", "demo", "staging")
BINDINGS = (TrafficPortBinding(42699, 18080),)
PREVIOUS_ID = "a" * 64
CANDIDATE_ID = "c" * 64


def _snapshot():
    header = (
        "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
        "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
        "srv_check_result srv_check_health srv_check_state srv_agent_state "
        "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
        "srv_check_port srv_check_addr srv_agent_addr srv_agent_port"
    )
    rows = [
        "1 be_p42699 1 slot_a 172.18.0.2 0 0 0 0 0 6 0 0 6 0 0 0 - 18080 - 0 18080 172.18.0.2 - 0",
        "1 be_p42699 2 slot_b 127.0.0.1 0 0 0 0 0 6 0 0 6 0 0 0 - 18080 - 0 18080 127.0.0.1 - 0",
    ]
    return "1\n" + header + "\n" + "\n".join(rows) + "\n"


def _artifact(version, digest):
    return DeploymentArtifact("docker-local", "sha256:" + digest, digest, version)


def _deployment(deployment_id, version, digest, runtime_id, status):
    return DeploymentRecord(
        deployment_id=deployment_id,
        provider="docker-local",
        project="demo",
        environment="staging",
        version=version,
        artifact=_artifact(version, digest),
        status=status,
        health_status="healthy" if status == "running" else "unknown",
        created_at="2026-11-17T12:00:00Z",
        container_id=runtime_id,
    )


class FakeDocker:
    name = "docker-local"

    def __init__(self):
        self.stopped = set()

    def inspect_runtime(self, record):
        stopped = record.container_id in self.stopped
        return SimpleNamespace(
            status="verified",
            observed_runtime_id=record.container_id,
            runtime_state="exited" if stopped else "running",
            health_status="unhealthy" if stopped else "healthy",
            checked_at="2026-11-17T12:01:00Z",
            probe="fake immutable Docker inspect",
            detail="",
        )

    def _execute(self, argv):
        if argv[0] == "stop" and len(argv) == 4 and argv[-1] in {PREVIOUS_ID, CANDIDATE_ID}:
            self.stopped.add(argv[-1])
            return DockerCommandResult(0, argv[-1], ""), None
        return None, "unexpected Docker command"


class FakeAppManager:
    def __init__(self, provider, targets):
        self.provider = provider
        self.targets = targets
        self.candidate_target = targets["candidate"]

    def ensure_app(self, spec, artifact):
        return SimpleNamespace(
            status="created",
            target=self.candidate_target,
            health_status="healthy",
            detail="",
            health_detail="",
            route_eligible=True,
        )

    def _inspect(self, spec):
        target = self.targets[spec.deployment_id]
        return (
            "verified",
            SimpleNamespace(
                status="verified",
                target=target,
                route_eligible=True,
                health_status="healthy",
                health_detail="",
            ),
            "",
        )


class FakeSlotManager:
    def __init__(self, provider, state_store):
        self.provider = provider
        self.state_store = state_store
        self.calls = []

    def prepare_inactive_slot(self, **kwargs):
        self.calls.append("prepare")
        return SimpleNamespace(status="verified", state_record=kwargs["state_record"])

    def switch_active_slot(self, **kwargs):
        self.calls.append("switch")
        result = self.state_store.persist_active_slot_map(
            kwargs["state_record"],
            expected_active_slot=kwargs["expected_active_slot"],
            active_slot=kwargs["slot"],
        )
        assert result.status == "persisted"
        return SimpleNamespace(status="verified", state_record=result.record)

    def drain_inactive_slot(self, **kwargs):
        self.calls.append(("drain", kwargs["slot"]))
        result = self.state_store.persist_servers_state(
            kwargs["state_record"], BINDINGS, _snapshot()
        )
        assert result.status == "persisted"
        return SimpleNamespace(status="verified", state_record=result.record)


class FakeRouterHost:
    def __init__(self, provider, history, network, image, initial_spec, state_root):
        self.provider = provider
        self.history = history
        self.network = network
        self.image = image
        self.initial_spec = initial_spec
        self.state_root = state_root

    @staticmethod
    def _validate_bindings(bindings):
        return tuple(sorted(bindings, key=lambda item: item.host_port))

    def ensure_router(self, scope, port_bindings):
        record = self.history.get_traffic_router(scope)
        state = self.history.get_traffic_router_state_record(scope)
        if record is None or state is None:
            return SimpleNamespace(status="failed", detail="Router registry missing")
        spec = build_router_container_spec(
            scope, port_bindings, self.network, self.image, state,
            expected_active_slot=record.active_slot,
        )
        return SimpleNamespace(
            status="ready",
            router_record=record,
            state_record=state,
            network=self.network,
            image=self.image,
            container_spec=spec,
        )


class FakeRuntimeAPI:
    def __init__(self, provider, router_id):
        self.provider = provider
        self.router_id = router_id

    def execute(self, command):
        if command.operation == "show_maps":
            return SimpleNamespace(
                status="succeeded",
                response=f"0 ({HAPROXY_ACTIVE_SLOT_MAP}) type=map\n",
                detail="",
            )
        if command.operation == "get_map":
            record = self.provider.history.get_traffic_router(self.provider.scope)
            return SimpleNamespace(
                status="succeeded",
                response=f"type=ip,type=string,found=yes,key=active,value={record.active_slot}\n",
                detail="",
            )
        return SimpleNamespace(status="failed", response="", detail="unexpected Runtime API operation")


def _setup(tmp_path, monkeypatch):
    history = DeploymentHistoryStore(tmp_path / "history.db")
    state_store = LocalDockerRouterStateStore(tmp_path / "router-state")
    network_spec = build_router_network_spec(SCOPE)
    network = DockerRouterNetworkRecord(
        network_spec.network_name, "b" * 64, network_spec.scope_fingerprint,
        "bridge", False, False,
    )
    image = DockerRouterImageIdentity(
        "sha256:" + "d" * 64, "linux", "amd64",
        ROUTER_HAPROXY_VERSION, ROUTER_SOCAT_PACKAGE_VERSION,
        ROUTER_BASE_IMAGE_REF, "1",
    )
    initial_state = state_store.persist(SCOPE, BINDINGS)
    assert initial_state.status == "persisted"
    server_state = state_store.persist_servers_state(
        initial_state.record, BINDINGS, _snapshot()
    )
    assert server_state.status == "persisted"
    initial_router = TrafficRouterRecord(
        scope=SCOPE,
        router_deployment_id="router-demo-staging",
        router_runtime_id="e" * 64,
        network_name=network.network_name,
        network_id=network.network_id,
        port_bindings=BINDINGS,
        active_slot=None,
        active_target=None,
        route_generation="generation-0",
        created_at="2026-11-17T12:00:00Z",
        slot_targets=(),
    )
    history.create_traffic_router(initial_router, server_state.record)
    active_state = state_store.persist_active_slot_map(
        server_state.record, expected_active_slot=None, active_slot="slot_a"
    )
    assert active_state.status == "persisted"
    previous_target = TrafficRouteTarget(
        "previous", PREVIOUS_ID, "172.18.0.2", BINDINGS
    )
    active_router = replace(
        initial_router,
        active_slot="slot_a",
        active_target=previous_target,
        slot_targets=(("slot_a", previous_target),),
        route_generation="generation-1",
    )
    history.update_traffic_router(
        active_router,
        active_state.record,
        expected_generation="generation-0",
        expected_state_map_sha256=server_state.record.active_slot_map_sha256,
    )
    initial_spec = build_router_container_spec(
        SCOPE, BINDINGS, network, image, active_state.record,
        expected_active_slot="slot_a",
    )
    docker = FakeDocker()
    app_target = TrafficRouteTarget(
        "candidate", CANDIDATE_ID, "172.18.0.3", BINDINGS
    )
    app_manager = FakeAppManager(
        docker, {"previous": previous_target, "candidate": app_target}
    )
    slot_manager = FakeSlotManager(docker, state_store)
    host = FakeRouterHost(
        docker, history, network, image, initial_spec, tmp_path / "router-state"
    )
    monkeypatch.setattr(
        adapter_module, "HAProxyRuntimeAPIClient",
        lambda provider, router_id: FakeRuntimeAPI(provider, router_id),
    )
    adapter = LocalDockerRouterReplacementProvider(
        docker, history, host, app_manager, slot_manager, SCOPE, BINDINGS
    )
    previous = _deployment("previous", "1.0", "1" * 64, PREVIOUS_ID, "running")
    candidate = _deployment("candidate", "2.0", "2" * 64, None, "prepared")
    history.append(previous)
    history.set_active_deployment(
        provider="docker-local",
        project="demo",
        environment="staging",
        deployment_id="previous",
        expected_deployment_id=None,
    )
    manager = HostDeploymentReplacementManager(
        adapter,
        history,
        clock=lambda: "2026-11-17T12:02:00Z",
        operation_id_factory=lambda: "router-replace-operation-1",
    )
    request = DeploymentRequest(
        project_root=str(tmp_path),
        project="demo",
        environment="staging",
        version="2.0",
    )
    return history, adapter, manager, request, previous, candidate, docker, slot_manager


def test_durable_replacement_coordinator_switches_router_then_drains_and_retires_previous(
    tmp_path, monkeypatch
):
    history, adapter, manager, request, previous, candidate, docker, slots = _setup(
        tmp_path, monkeypatch
    )

    result = manager.replace(request, candidate)

    assert result.status == "replaced", result.message
    assert result.phase == "previous_retired"
    assert result.record is not None
    assert result.record.deployment_id == "candidate"
    assert docker.stopped == {PREVIOUS_ID}
    assert slots.calls == ["prepare", "switch", ("drain", "slot_a")]
    assert history.active_deployment(
        provider="docker-local", project="demo", environment="staging"
    ).deployment_id == "candidate"
    assert history.get("previous").status == "stopped"
    assert history.get("candidate").status == "running"
    router = history.get_traffic_router(SCOPE)
    assert router.active_slot == "slot_b"
    assert router.active_target.runtime_id == CANDIDATE_ID
    assert router.slot_targets == (("slot_b", router.active_target),)
    assert adapter.read_traffic_target(request) == CANDIDATE_ID
