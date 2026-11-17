from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.deployment_traffic_router import (
    TrafficPortBinding,
    TrafficRouteReadback,
    TrafficRouteTarget,
    TrafficPortObservation,
    TrafficRouterRecord,
    TrafficRouterScope,
    TrafficRouterOperationResult,
    TrafficSlotConnectionSnapshot,
)


def _scope():
    return TrafficRouterScope("docker-local", "demo", "staging")


def _bindings():
    return (
        TrafficPortBinding(8080, 80),
        TrafficPortBinding(8443, 443),
    )


def _target(runtime_id="a" * 64, address="172.20.0.4", deployment_id="candidate"):
    return TrafficRouteTarget(deployment_id, runtime_id, address, _bindings())


def _router(active_slot="slot_a", active_target=None):
    if active_target is None and active_slot is not None:
        active_target = _target("b" * 64, "172.20.0.3", "previous")
    slot_targets = (
        ((active_slot, active_target),)
        if active_slot is not None and active_target is not None
        else ()
    )
    return TrafficRouterRecord(
        scope=_scope(),
        router_deployment_id="router-demo-staging",
        router_runtime_id="c" * 64,
        network_name="ai-team-scope-12ab34",
        port_bindings=_bindings(),
        active_slot=active_slot,
        active_target=active_target,
        route_generation="generation-001",
        created_at="2026-11-15T16:00:00Z",
        slot_targets=slot_targets,
    )


def _verified_readback(target=None):
    target = target or _target()
    observations = tuple(
        TrafficPortObservation(
            host_port=binding.host_port,
            protocol="tcp",
            slot="slot_b",
            deployment_id=target.deployment_id,
            runtime_id=target.runtime_id,
            address=target.address,
            container_port=binding.container_port,
            backend_state="up",
            active_connections=0,
        )
        for binding in target.port_bindings
    )
    return TrafficRouteReadback(
        scope=_scope(),
        status="verified",
        expected_router_runtime_id="c" * 64,
        observed_router_runtime_id="c" * 64,
        expected_generation="generation-002",
        observed_generation="generation-002",
        expected_slot="slot_b",
        observed_slot="slot_b",
        expected_target=target,
        observed_target_runtime_id=target.runtime_id,
        observed_target_address=target.address,
        port_observations=observations,
        checked_at="2026-11-15T16:01:00Z",
    )


@pytest.mark.parametrize("port", [0, -1, 65536, True, 80.0])
def test_port_binding_rejects_invalid_port_values(port):
    with pytest.raises(ValueError, match="1..65535"):
        TrafficPortBinding(port, 80)


def test_port_binding_rejects_udp_instead_of_silently_falling_back():
    with pytest.raises(ValueError, match="only TCP"):
        TrafficPortBinding(8080, 80, "udp")


def test_target_requires_full_immutable_runtime_id_and_literal_ip():
    with pytest.raises(ValueError, match="immutable runtime ID"):
        TrafficRouteTarget("candidate", "container-name", "172.20.0.4", _bindings())
    with pytest.raises(ValueError, match="literal IPv4 or IPv6"):
        TrafficRouteTarget("candidate", "a" * 64, "candidate.local", _bindings())


def test_target_requires_unique_host_ports():
    with pytest.raises(ValueError, match="host ports must be unique"):
        TrafficRouteTarget(
            "candidate",
            "a" * 64,
            "172.20.0.4",
            (TrafficPortBinding(8080, 80), TrafficPortBinding(8080, 81)),
        )


def test_router_requires_immutable_identity_and_active_slot_target_pair():
    with pytest.raises(ValueError, match="immutable runtime ID"):
        TrafficRouterRecord(
            _scope(), "router", "router-name", "network",
            _bindings(), "slot_a", _target(), "gen", "2026-11-15T16:00:00Z"
        )
    with pytest.raises(ValueError, match="both be set or both be absent"):
        replace(_router(), active_slot=None)


def test_router_target_port_contract_must_match_scope():
    wrong_target = TrafficRouteTarget(
        "previous", "b" * 64, "172.20.0.3", (TrafficPortBinding(8080, 8081),)
    )
    with pytest.raises(ValueError, match="bindings must match"):
        replace(_router(), active_target=wrong_target)


def test_verified_readback_requires_exact_router_generation_slot_and_target():
    assert _verified_readback().status == "verified"
    with pytest.raises(ValueError, match="router, generation, slot and target"):
        replace(_verified_readback(), observed_generation="stale-generation")
    with pytest.raises(ValueError, match="router, generation, slot and target"):
        replace(_verified_readback(), observed_target_runtime_id="d" * 64)


def test_verified_readback_requires_every_port_and_healthy_backend():
    readback = _verified_readback()
    with pytest.raises(ValueError, match="exactly one observation per host port"):
        replace(readback, port_observations=readback.port_observations[:1])
    first = replace(readback.port_observations[0], backend_state="down")
    with pytest.raises(ValueError, match="mismatched or unhealthy"):
        replace(readback, port_observations=(first, readback.port_observations[1]))


def test_non_verified_readback_can_report_unknown_route_without_claiming_success():
    readback = TrafficRouteReadback(
        scope=_scope(),
        status="unavailable",
        expected_router_runtime_id="c" * 64,
        observed_router_runtime_id=None,
        expected_generation="generation-002",
        observed_generation=None,
        expected_slot="slot_b",
        observed_slot=None,
        expected_target=_target(),
        observed_target_runtime_id=None,
        observed_target_address=None,
        port_observations=(),
        checked_at="2026-11-15T16:01:00Z",
        detail="Router admin socket unavailable",
    )
    assert readback.status == "unavailable"


def test_verified_connection_snapshot_requires_known_nonnegative_count():
    snapshot = TrafficSlotConnectionSnapshot(
        "c" * 64, "slot_a", "verified", "drain", 0, "2026-11-15T16:02:00Z"
    )
    assert snapshot.active_connections == 0
    with pytest.raises(ValueError, match="non-negative"):
        replace(snapshot, active_connections=-1)
    with pytest.raises(ValueError, match="known drain state and count"):
        replace(snapshot, status="verified", active_connections=None, drain_state="unknown")


def test_router_operation_result_rejects_unknown_status_and_bad_identity():
    result = TrafficRouterOperationResult(
        "operation-001", "switch_active_slot", "succeeded",
        "c" * 64, "generation-002", "slot_b"
    )
    assert result.status == "succeeded"
    with pytest.raises(ValueError, match="router operation status"):
        replace(result, status="complete")
    with pytest.raises(ValueError, match="immutable runtime ID"):
        replace(result, router_runtime_id="router-name")
