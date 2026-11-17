from __future__ import annotations

import pytest

from runtime.haproxy_runtime_readback import (
    ExpectedHAProxyServer,
    parse_show_servers_state,
    parse_show_stat_servers,
    parse_get_map_value,
    verify_inactive_slot_readback,
)


_STATE_HEADER = (
    "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
    "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
    "srv_check_result srv_check_health srv_check_state srv_agent_state "
    "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
    "srv_check_port srv_check_addr srv_agent_addr srv_agent_port"
)


def state_row(
    server="slot_b",
    *,
    address="172.18.0.2",
    port=18080,
    op_state=2,
    admin_state=0,
    check_result=3,
    check_state=6,
):
    return (
        f"1 be_p8080 2 {server} {address} {op_state} {admin_state} "
        f"0 0 1 6 {check_result} 2 {check_state} 0 0 0 - {port} - 0 "
        f"{port} {address} - 0"
    )


def state_response(*rows):
    return "1\n" + _STATE_HEADER + "\n" + "\n".join(rows) + "\n"


def stat_response(*rows):
    return (
        "# pxname,svname,scur,status\n"
        + "\n".join(f"be_p8080,{server},{sessions},{status}" for server, sessions, status in rows)
        + "\n"
    )


def expected():
    return (ExpectedHAProxyServer("be_p8080", "slot_b", "172.18.0.2", 18080),)


def test_parse_show_servers_state_uses_header_not_fixed_column_indexes():
    header = _STATE_HEADER.replace("srv_port", "srv_extra srv_port")
    row = state_row().replace(" 18080 - 0", " extra 18080 - 0")
    parsed = parse_show_servers_state("1\n" + header + "\n" + row + "\n")
    assert len(parsed) == 1
    assert parsed[0].backend == "be_p8080"
    assert parsed[0].server == "slot_b"
    assert parsed[0].address == "172.18.0.2"
    assert parsed[0].port == 18080
    assert parsed[0].fully_up_and_enabled is True


def test_parse_show_stat_servers_extracts_status_and_current_sessions():
    parsed = parse_show_stat_servers(stat_response(("slot_b", 4, "UP")))
    assert len(parsed) == 1
    assert parsed[0].backend == "be_p8080"
    assert parsed[0].server == "slot_b"
    assert parsed[0].status == "UP"
    assert parsed[0].current_sessions == 4


def test_inactive_slot_readback_verifies_exact_address_port_up_and_scur():
    result = verify_inactive_slot_readback(
        expected(),
        servers_state_response=state_response(state_row()),
        stat_response=stat_response(("slot_b", 4, "UP")),
    )
    assert result.status == "verified"
    assert result.observations[0].current_sessions == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {"address": "172.18.0.3"},
        {"port": 18081},
        {"op_state": 1},
        {"admin_state": 8},
        {"admin_state": 1},
        {"check_result": 2},
        {"check_state": 2},
    ],
)
def test_inactive_slot_readback_fails_closed_on_endpoint_or_server_state(kwargs):
    result = verify_inactive_slot_readback(
        expected(),
        servers_state_response=state_response(state_row(**kwargs)),
        stat_response=stat_response(("slot_b", 0, "UP")),
    )
    assert result.status == "mismatch"


def test_inactive_slot_readback_rejects_down_or_missing_stat_server():
    down = verify_inactive_slot_readback(
        expected(),
        servers_state_response=state_response(state_row()),
        stat_response=stat_response(("slot_b", 0, "DOWN")),
    )
    assert down.status == "mismatch"
    missing = verify_inactive_slot_readback(
        expected(),
        servers_state_response=state_response(state_row()),
        stat_response=stat_response(("other", 0, "UP")),
    )
    assert missing.status == "mismatch"


@pytest.mark.parametrize(
    "response",
    [
        "",
        "2\n" + _STATE_HEADER + "\n" + state_row() + "\n",
        "1\n" + state_row() + "\n",
        "1\n" + _STATE_HEADER + "\n",
        "1\n" + _STATE_HEADER.replace("srv_port", "srv_name") + "\n" + state_row() + "\n",
        state_response(state_row(), state_row()),
        "1\n" + _STATE_HEADER + "\n" + state_row().replace("172.18.0.2", "invalid-ip") + "\n",
    ],
)
def test_parse_show_servers_state_rejects_malformed_or_ambiguous_responses(response):
    with pytest.raises(ValueError):
        parse_show_servers_state(response)


@pytest.mark.parametrize(
    "response",
    [
        "",
        "# pxname,svname,status\nbe_p8080,slot_b,UP\n",
        "# pxname,svname,scur,status\nbe_p8080,slot_b,-1,UP\n",
        "# pxname,svname,scur,status\nbe_p8080,slot_b,0,UP,extra\n",
        "# pxname,svname,scur,status\nbe_p8080,slot_b,0,UP\nbe_p8080,slot_b,0,UP\n",
    ],
)
def test_parse_show_stat_servers_rejects_malformed_or_ambiguous_csv(response):
    with pytest.raises(ValueError):
        parse_show_stat_servers(response)


def test_expected_server_rejects_noncanonical_or_unbounded_endpoint():
    with pytest.raises(ValueError):
        ExpectedHAProxyServer("be_p8080", "slot_b", "172.018.0.2", 18080)
    with pytest.raises(ValueError):
        ExpectedHAProxyServer("be_p8080", "slot_b", "172.18.0.2", True)


def test_parse_get_map_value_returns_the_current_known_selector_without_expected_value():
    response = (
        'type=beg, case=sensitive, found=yes, idx=tree, '
        'key="active", value="slot_b", type="str"\n'
    )
    assert parse_get_map_value(response, expected_key="active") == "slot_b"


@pytest.mark.parametrize("value", ["unexpected", "slot_c", ""])
def test_parse_get_map_value_rejects_unknown_selector_values(value):
    response = (
        'type=beg, found=yes, key="active", value="' + value + '"'
    )
    with pytest.raises(ValueError):
        parse_get_map_value(response, expected_key="active")
