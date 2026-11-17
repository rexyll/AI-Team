
"""Deterministic, data-only HAProxy TCP router configuration rendering.

No Docker process, filesystem write, HAProxy Runtime API call, or route switch
is performed here. All generated server names, map paths, and selectors are
Host-owned constants derived only from validated TCP port bindings.
"""
from __future__ import annotations

from runtime.deployment_traffic_router import RouterSlot, TrafficPortBinding

HAPROXY_ADMIN_SOCKET = "/run/haproxy/admin.sock"
HAPROXY_STATE_DIRECTORY = "/usr/local/etc/haproxy"
HAPROXY_CONFIG_FILE = f"{HAPROXY_STATE_DIRECTORY}/haproxy.cfg"
HAPROXY_ACTIVE_SLOT_MAP = f"{HAPROXY_STATE_DIRECTORY}/active-slot.map"
HAPROXY_SERVERS_STATE_FILE = f"{HAPROXY_STATE_DIRECTORY}/servers-state"
HAPROXY_INITIAL_PLACEHOLDER_ADDRESS = "127.0.0.1"
HAPROXY_INITIAL_PLACEHOLDER_PORT = 1
HAPROXY_INITIAL_SERVER_WEIGHT = 0


def _validated_bindings(
    port_bindings: tuple[TrafficPortBinding, ...],
) -> tuple[TrafficPortBinding, ...]:
    if not isinstance(port_bindings, tuple) or not port_bindings:
        raise ValueError("port_bindings must be a non-empty tuple")
    if any(not isinstance(item, TrafficPortBinding) for item in port_bindings):
        raise TypeError("port_bindings must contain TrafficPortBinding values")
    host_ports = [item.host_port for item in port_bindings]
    if len(host_ports) != len(set(host_ports)):
        raise ValueError("host ports must be unique within one Router scope")
    return tuple(sorted(port_bindings, key=lambda item: item.host_port))


def render_active_slot_map(active_slot: RouterSlot | None) -> str:
    """Render the selector file; None deliberately matches neither slot."""
    if active_slot not in {None, "slot_a", "slot_b"}:
        raise ValueError("active_slot must be slot_a, slot_b, or None")
    value = active_slot if active_slot is not None else "none"
    return f"active {value}\n"


def render_haproxy_router_config(
    port_bindings: tuple[TrafficPortBinding, ...],
) -> str:
    """Render TCP frontends with a shared active-slot selector and no fallback.

    Both servers have weight 0. Only an explicit use-server rule can select a
    slot; an absent selector or unavailable selected server cannot fall back
    through the normal load-balancing scheduler.
    """
    bindings = _validated_bindings(port_bindings)
    lines = [
        "global",
        "    log stdout format raw local0",
        "    maxconn 4096",
        f"    stats socket {HAPROXY_ADMIN_SOCKET} mode 600 level admin",
        f"    server-state-file {HAPROXY_SERVERS_STATE_FILE}",
        "",
        "defaults",
        "    log global",
        "    load-server-state-from-file global",
        "    mode tcp",
        "    option tcplog",
        "    timeout connect 5s",
        "    timeout client 1h",
        "    timeout server 1h",
        "    timeout tunnel 1h",
    ]
    for binding in bindings:
        port = binding.host_port
        frontend = f"fe_p{port}"
        backend = f"be_p{port}"
        acl_a = f"active_slot_a_p{port}"
        acl_b = f"active_slot_b_p{port}"
        lines.extend([
            "",
            f"frontend {frontend}",
            f"    bind 0.0.0.0:{port}",
            f"    default_backend {backend}",
            "",
            f"backend {backend}",
            f"    acl {acl_a} str(active),map({HAPROXY_ACTIVE_SLOT_MAP}) -m str slot_a",
            f"    use-server slot_a if {acl_a}",
            f"    acl {acl_b} str(active),map({HAPROXY_ACTIVE_SLOT_MAP}) -m str slot_b",
            f"    use-server slot_b if {acl_b}",
            (
                f"    server slot_a {HAPROXY_INITIAL_PLACEHOLDER_ADDRESS}:"
                f"{HAPROXY_INITIAL_PLACEHOLDER_PORT} check weight "
                f"{HAPROXY_INITIAL_SERVER_WEIGHT} inter 1s fall 2 rise 2 "
                "init-addr last,libc,none"
            ),
            (
                f"    server slot_b {HAPROXY_INITIAL_PLACEHOLDER_ADDRESS}:"
                f"{HAPROXY_INITIAL_PLACEHOLDER_PORT} check weight "
                f"{HAPROXY_INITIAL_SERVER_WEIGHT} inter 1s fall 2 rise 2 "
                "init-addr last,libc,none"
            ),
        ])
    return "\n".join(lines) + "\n"
