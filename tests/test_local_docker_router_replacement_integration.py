from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.deployment_history import DeploymentHistoryStore
from runtime.deployment_provider import (
    DeploymentArtifact,
    DeploymentRecord,
    DeploymentRuntimeInspection,
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
        self.identity_mismatch_ids = set()

    def inspect_runtime(self, record):
        if record.container_id in self.identity_mismatch_ids:
            return DeploymentRuntimeInspection(
                provider=self.name,
                deployment_id=record.deployment_id,
                expected_runtime_id=record.container_id,
                observed_runtime_id=CANDIDATE_ID,
                identity_match=False,
                status="identity_mismatch",
                runtime_state="unknown",
                health_status="unavailable",
                checked_at="2026-11-17T12:01:00Z",
                probe="fake immutable Docker inspect",
                detail="Docker inspect returned a different immutable container ID",
            )
        stopped = record.container_id in self.stopped
        return DeploymentRuntimeInspection(
            provider=self.name,
            deployment_id=record.deployment_id,
            expected_runtime_id=record.container_id,
            observed_runtime_id=record.container_id,
            identity_match=True,
            status="verified",
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
    def __init__(
        self, provider, state_store, runtime_state, *,
        drain_status="verified", identity_mismatch_on_drain=False,
        drain_remaining_connections=0,
    ):
        self.provider = provider
        self.state_store = state_store
        self.runtime_state = runtime_state
        self.drain_status = drain_status
        self.identity_mismatch_on_drain = identity_mismatch_on_drain
        self.drain_remaining_connections = drain_remaining_connections
        self.last_drained_state_record = None
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
        self.runtime_state["selector"] = kwargs["slot"]
        return SimpleNamespace(status="verified", state_record=result.record)

    def drain_inactive_slot(self, **kwargs):
        self.calls.append(("drain", kwargs["slot"]))
        if self.drain_status != "verified":
            return SimpleNamespace(
                status=self.drain_status, state_record=None,
                remaining_connections=self.drain_remaining_connections,
                detail=(
                    "injected connection drain timeout; "
                    f"remaining_connections={self.drain_remaining_connections}"
                ),
            )
        result = self.state_store.persist_servers_state(
            kwargs["state_record"], BINDINGS, _snapshot()
        )
        assert result.status == "persisted"
        self.last_drained_state_record = result.record
        if self.identity_mismatch_on_drain and kwargs["slot"] == "slot_a":
            self.provider.identity_mismatch_ids.add(PREVIOUS_ID)
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

    def inspect_existing_scope_readonly(self, scope, port_bindings):
        return self.ensure_router(scope, port_bindings)


class FakeRuntimeAPI:
    def __init__(self, history, scope, runtime_state):
        self.history = history
        self.scope = scope
        self.runtime_state = runtime_state

    def execute(self, command):
        if command.operation == "show_maps":
            return SimpleNamespace(
                status="succeeded",
                response=f"0 ({HAPROXY_ACTIVE_SLOT_MAP}) type=map\n",
                detail="",
            )
        if command.operation == "get_map":
            return SimpleNamespace(
                status="succeeded",
                response=f"type=ip,type=string,found=yes,key=active,value={self.runtime_state['selector']}\n",
                detail="",
            )
        if command.operation in {"show_servers_state", "show_stat_servers"}:
            record = self.history.get_traffic_router(self.scope)
            backend = command.line.split()[-1]
            binding = next(
                item for item in record.port_bindings
                if f"be_p{item.host_port}" == backend
            )
            slot_targets = dict(record.slot_targets)
            if command.operation == "show_servers_state":
                header = _snapshot().splitlines()[1]
                rows = []
                for server_id, slot in enumerate(("slot_a", "slot_b"), start=1):
                    target = slot_targets.get(slot)
                    if target is None:
                        address, port = "-", 1
                        op_state, admin_state, check_result, check_state = 0, 0, 0, 0
                    else:
                        target_binding = next(
                            item for item in target.port_bindings
                            if item.host_port == binding.host_port
                            and item.protocol == binding.protocol
                        )
                        address, port = target.address, target_binding.container_port
                        op_state, admin_state, check_result, check_state = 2, 0, 3, 0x06
                    rows.append(
                        f"1 {backend} {server_id} {slot} {address} {op_state} {admin_state} "
                        f"0 0 0 6 {check_result} 0 {check_state} 0 0 0 - {port} - 0 "
                        f"{port} {address} - 0"
                    )
                response = "1\n" + header + "\n" + "\n".join(rows) + "\n"
            else:
                header = "# pxname,svname,status,scur"
                rows = [
                    f"{backend},{slot},{'UP' if slot in slot_targets else 'DOWN'},0"
                    for slot in ("slot_a", "slot_b")
                ]
                response = header + "\n" + "\n".join(rows) + "\n"
            return SimpleNamespace(status="succeeded", response=response, detail="")
        return SimpleNamespace(status="failed", response="", detail="unexpected Runtime API operation")


def _setup(
    tmp_path, monkeypatch, *,
    drain_status="verified", identity_mismatch_on_stop=False,
    drain_remaining_connections=0,
):
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
    runtime_state = {"selector": "slot_a"}
    slot_manager = FakeSlotManager(
        docker, state_store, runtime_state,
        drain_status=drain_status,
        identity_mismatch_on_drain=identity_mismatch_on_stop,
        drain_remaining_connections=drain_remaining_connections,
    )
    host = FakeRouterHost(
        docker, history, network, image, initial_spec, tmp_path / "router-state"
    )
    adapter = LocalDockerRouterReplacementProvider(
        docker, history, host, app_manager, slot_manager, SCOPE, BINDINGS
    )
    monkeypatch.setattr(
        adapter_module, "HAProxyRuntimeAPIClient",
        lambda provider, router_id: FakeRuntimeAPI(history, SCOPE, runtime_state),
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


class SimulatedProcessCrash(BaseException):
    pass


def test_crash_after_provider_switch_requires_read_only_manual_reconciliation(
    tmp_path, monkeypatch
):
    history, adapter, manager, request, previous, candidate, docker, slots = _setup(
        tmp_path, monkeypatch
    )
    real_switch = adapter.switch_traffic
    switch_calls = []

    def switch_then_interrupt(*args, **kwargs):
        switch_calls.append("called")
        result = real_switch(*args, **kwargs)
        assert result.status == "succeeded", result.message
        raise SimulatedProcessCrash("process interrupted after provider switch")

    adapter.switch_traffic = switch_then_interrupt
    with pytest.raises(SimulatedProcessCrash):
        manager.replace(request, candidate)

    journal = history.get_replacement("router-replace-operation-1")
    assert len(switch_calls) == 1
    assert journal.phase == "traffic_switch_pending"
    assert journal.effective_traffic_target is None
    assert docker.stopped == set()
    assert history.get("previous").status == "running"
    assert history.get("candidate").status == "running"
    assert history.active_deployment(
        provider="docker-local", project="demo", environment="staging"
    ).deployment_id == "previous"
    router = history.get_traffic_router(SCOPE)
    assert router.active_slot == "slot_b"
    assert router.active_target.runtime_id == CANDIDATE_ID
    assert {slot for slot, _ in router.slot_targets} == {"slot_a", "slot_b"}
    assert adapter.read_traffic_target(request) == CANDIDATE_ID
    assert slots.calls == ["prepare", "switch"]

    inventory = manager.recovery_inventory(project="demo", environment="staging")
    assert len(inventory) == 1
    assert inventory[0].classification == "switch_intent_requires_inspection"
    assert inventory[0].phase == "traffic_switch_pending"
    assert inventory[0].active_deployment_id == "previous"
    assert inventory[0].external_state_verified is False
    assert inventory[0].automatic_recovery_allowed is False
    assert inventory[0].recovery_assessment.disposition == "manual_reconciliation_required"
    assert inventory[0].recovery_assessment.automatic_action == "none"
    assert "read_back_effective_traffic_target" in inventory[0].recovery_assessment.required_checks

    runtimes = manager.inspect_recovery_runtimes(project="demo", environment="staging")
    assert len(runtimes) == 1
    assert runtimes[0].phase == "traffic_switch_pending"
    # Runtime inspection is deliberately deferred for a pending switch intent;
    # recovery inventory must not claim external state is already reconciled.
    assert runtimes[0].previous_runtime is None
    assert runtimes[0].candidate_runtime is None
    assert runtimes[0].route_readback_status == "not_available"
    assert runtimes[0].automatic_recovery_allowed is False
    previous_inspection = docker.inspect_runtime(history.get("previous"))
    candidate_inspection = docker.inspect_runtime(history.get("candidate"))
    assert previous_inspection.status == "verified"
    assert previous_inspection.observed_runtime_id == PREVIOUS_ID
    assert previous_inspection.runtime_state == "running"
    assert candidate_inspection.status == "verified"
    assert candidate_inspection.observed_runtime_id == CANDIDATE_ID
    assert candidate_inspection.runtime_state == "running"

    readbacks = manager.manual_reconciliation_readback(
        project="demo", environment="staging"
    )
    assert len(readbacks) == 1
    report = readbacks[0]
    assert report.operation_id == journal.operation_id
    assert report.phase == "traffic_switch_pending"
    assert report.inventory_classification == "switch_intent_requires_inspection"
    assert report.durable_active_deployment_id == "previous"
    assert report.assessment == "switch_applied_before_journal_commit", (
        f"route_readback={report.route_readback!r}; "
        f"previous_runtime={report.previous_runtime!r}; "
        f"candidate_runtime={report.candidate_runtime!r}"
    )
    assert report.previous_runtime.status == "verified"
    assert report.previous_runtime.observed_runtime_id == PREVIOUS_ID
    assert report.previous_runtime.runtime_state == "running"
    assert report.previous_runtime.health_status == "healthy"
    assert report.candidate_runtime.status == "verified"
    assert report.candidate_runtime.observed_runtime_id == CANDIDATE_ID
    assert report.candidate_runtime.runtime_state == "running"
    assert report.candidate_runtime.health_status == "healthy"
    assert report.route_readback.status == "verified"
    assert report.route_readback.registry_active_slot == "slot_b"
    assert report.route_readback.live_active_slot == "slot_b"
    assert report.route_readback.registry_active_runtime_id == CANDIDATE_ID
    assert report.route_readback.effective_runtime_id == CANDIDATE_ID
    assert len(report.route_readback.backend_readbacks) == 1
    backend = report.route_readback.backend_readbacks[0]
    assert backend.backend == "be_p42699"
    assert backend.slot == "slot_b"
    assert backend.expected_address == "172.18.0.3"
    assert backend.observed_address == "172.18.0.3"
    assert backend.expected_port == 18080
    assert backend.observed_port == 18080
    assert backend.status == "UP"
    assert backend.current_sessions == 0
    assert report.automatic_action == "none"
    assert report.automatic_recovery_allowed is False

    # A report is observational only: journal, active pointer, selector and
    # runtime inventory remain exactly as they were before the read-back.
    assert history.get_replacement(journal.operation_id) == journal
    assert history.active_deployment(
        provider="docker-local", project="demo", environment="staging"
    ).deployment_id == "previous"
    assert history.get_traffic_router(SCOPE).active_slot == "slot_b"
    assert docker.stopped == set()
    assert slots.calls == ["prepare", "switch"]


def test_previous_identity_mismatch_keeps_digest_consistent_router_and_both_runtimes(
    tmp_path, monkeypatch
):
    history, adapter, manager, request, previous, candidate, docker, slots = _setup(
        tmp_path, monkeypatch, identity_mismatch_on_stop=True
    )

    result = manager.replace(request, candidate)

    assert result.status == "needs_reconciliation"
    assert result.phase == "needs_reconciliation"
    assert history.get_replacement("router-replace-operation-1").phase == "needs_reconciliation"
    assert docker.stopped == set()
    assert history.get("previous").status == "running"
    assert history.get("candidate").status == "running"
    active = history.active_deployment(
        provider="docker-local", project="demo", environment="staging"
    )
    assert active.deployment_id == "candidate"

    router = history.get_traffic_router(SCOPE)
    assert router.active_slot == "slot_b"
    assert router.active_target.runtime_id == CANDIDATE_ID
    assert {slot for slot, _ in router.slot_targets} == {"slot_a", "slot_b"}

    # The drained server-state file must be checkpointed before the stop gate.
    stored_state = history.get_traffic_router_state_record(SCOPE)
    assert slots.last_drained_state_record is not None
    assert stored_state == slots.last_drained_state_record
    assert stored_state.server_state_sha256 == hashlib.sha256(
        Path(stored_state.server_state_path).read_bytes()
    ).hexdigest()
    # Host read-back must remain available while the scope is held for reconciliation.
    assert adapter.read_traffic_target(request) == CANDIDATE_ID
    assert slots.calls == ["prepare", "switch", ("drain", "slot_a")]


def test_drain_timeout_keeps_previous_runtime_running_and_reserves_reconciliation(
    tmp_path, monkeypatch
):
    history, adapter, manager, request, previous, candidate, docker, slots = _setup(
        tmp_path, monkeypatch, drain_status="indeterminate",
        drain_remaining_connections=1,
    )

    result = manager.replace(request, candidate)

    assert result.status == "needs_reconciliation"
    assert "drain timeout" in result.message
    assert "remaining_connections=1" in result.message
    assert slots.drain_remaining_connections == 1
    assert docker.stopped == set()
    assert history.get("previous").status == "running"
    assert history.active_deployment(
        provider="docker-local", project="demo", environment="staging"
    ).deployment_id == "candidate"
    assert history.get_replacement("router-replace-operation-1").phase == "needs_reconciliation"
    assert slots.calls == ["prepare", "switch", ("drain", "slot_a")]
