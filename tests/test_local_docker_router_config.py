
from __future__ import annotations

import pytest

from runtime.deployment_traffic_router import TrafficPortBinding
from runtime.local_docker_router_config import (
    HAPROXY_ACTIVE_SLOT_MAP,
    HAPROXY_ADMIN_SOCKET,
    render_active_slot_map,
    render_haproxy_router_config,
)


def _bindings():
    return (
        TrafficPortBinding(8443, 443),
        TrafficPortBinding(8080, 80),
    )


def test_initial_active_slot_map_is_fail_closed():
    assert render_active_slot_map(None) == "active none\\n"
    assert render_active_slot_map("slot_a") == "active slot_a\\n"
    assert render_active_slot_map("slot_b") == "active slot_b\\n"
    with pytest.raises(ValueError, match="active_slot"):
        render_active_slot_map("previous")


def test_haproxy_config_has_stable_tcp_frontends_and_shared_map_selector():
    config = render_haproxy_router_config(_bindings())

    assert config.startswith("global\\n")
    assert f"stats socket {HAPROXY_ADMIN_SOCKET} mode 600 level admin" in config
    assert f"map({HAPROXY_ACTIVE_SLOT_MAP})" in config
    assert "frontend fe_p8080" in config
    assert "frontend fe_p8443" in config
    assert "bind 0.0.0.0:8080" in config
    assert "bind 0.0.0.0:8443" in config
    assert "default_backend be_p8080" in config
    assert "default_backend be_p8443" in config
    assert config.index("frontend fe_p8080") < config.index("frontend fe_p8443")


def test_each_backend_has_both_explicit_selectors_and_zero_weight_servers():
    config = render_haproxy_router_config(_bindings())

    for port in (8080, 8443):
        assert f"acl active_slot_a_p{port} str(active),map(" in config
        assert f"use-server slot_a if active_slot_a_p{port}" in config
        assert f"acl active_slot_b_p{port} str(active),map(" in config
        assert f"use-server slot_b if active_slot_b_p{port}" in config
        backend_start = config.index(f"backend be_p{port}")
        next_frontend = config.find("\\nfrontend ", backend_start)
        backend_text = config[backend_start:next_frontend if next_frontend >= 0 else None]
        assert backend_text.count("weight 0") == 2
        assert "server slot_a 127.0.0.1:1" in backend_text
        assert "server slot_b 127.0.0.1:1" in backend_text


def test_haproxy_config_rejects_empty_or_duplicate_host_ports():
    with pytest.raises(ValueError, match="non-empty tuple"):
        render_haproxy_router_config(())
    with pytest.raises(ValueError, match="host ports must be unique"):
        render_haproxy_router_config((
            TrafficPortBinding(8080, 80),
            TrafficPortBinding(8080, 81),
        ))


def test_haproxy_config_rejects_non_binding_values():
    with pytest.raises(TypeError, match="TrafficPortBinding"):
        render_haproxy_router_config(("8080:80",))


def test_rendered_config_does_not_enable_persistence_or_non_tcp_mode():
    config = render_haproxy_router_config(_bindings())
    assert "mode tcp" in config
    assert "cookie " not in config
    assert "stick-table" not in config
    assert "persist " not in config
    assert "balance " not in config


def test_config_generation_is_deterministic():
    bindings = _bindings()
    assert render_haproxy_router_config(bindings) == render_haproxy_router_config(
        tuple(reversed(bindings))
    )
