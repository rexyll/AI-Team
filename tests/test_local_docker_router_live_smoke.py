from __future__ import annotations

import pytest

from scripts.local_docker_router_live_smoke import (
    parse_get_map_value,
    parse_show_info,
    parse_show_map_registry,
)


def test_parse_show_info_accepts_the_pinned_haproxy_version():
    parsed = parse_show_info(
        "Name: HAProxy\nVersion: 3.4.7-abc123\nRelease_date: 2026/10/01\n"
    )
    assert parsed["Name"] == "HAProxy"
    assert parsed["Version"] == "3.4.7-abc123"


@pytest.mark.parametrize(
    "response",
    [
        "",
        "Version: 3.4.7\n",
        "Name: NotHAProxy\nVersion: 3.4.7\n",
        "Name: HAProxy\nVersion: 3.3.9\n",
        "Name: HAProxy\nName: HAProxy\nVersion: 3.4.7\n",
    ],
)
def test_parse_show_info_rejects_missing_duplicate_or_unpinned_identity(response):
    with pytest.raises(ValueError):
        parse_show_info(response)


def test_parse_show_map_registry_resolves_exact_active_map_id():
    response = (
        "# id (file) description\n"
        "0 (/etc/other.map) other map\n"
        "7 (/usr/local/etc/haproxy/active-slot.map) router map\n"
    )
    assert parse_show_map_registry(
        response, expected_path="/usr/local/etc/haproxy/active-slot.map"
    ) == "#7"


@pytest.mark.parametrize(
    "response",
    [
        "",
        "# id (file) description\n0 (/etc/other.map) other map\n",
        "0 (/usr/local/etc/haproxy/active-slot.map) first\n1 (/usr/local/etc/haproxy/active-slot.map) duplicate\n",
        "0 (relative.map) invalid\n",
    ],
)
def test_parse_show_map_registry_rejects_missing_or_ambiguous_map(response):
    with pytest.raises(ValueError):
        parse_show_map_registry(
            response, expected_path="/usr/local/etc/haproxy/active-slot.map"
        )


def test_parse_get_map_value_accepts_exact_active_none_entry():
    response = (
        'type=beg, case=sensitive, found=yes, idx=tree, '
        'key="active", value="none", type="str"\n'
    )
    assert parse_get_map_value(response, expected_key="active", expected_value="none") == "none"


@pytest.mark.parametrize(
    "response",
    [
        "",
        'type=str, case=sensitive, found=no, key="active", value="none"',
        'type=str, case=sensitive, found=yes, key="other", value="none"',
        'type=str, case=sensitive, found=yes, key="active", value="slot_a"',
        'type=str, found=yes, key="active", key="active", value="none"',
        'type=str, found=yes, key="active", found=no, value="none"',
        'type=str, found=yes, key="active", value="none", type="str", type="str"',
        'type=str, found=yes, key="active", value="none"\nextra',
        'type=str, found=yes, key="active", value="unterminated',
    ],
)
def test_parse_get_map_value_fails_closed_on_ambiguous_or_wrong_selector(response):
    with pytest.raises(ValueError):
        parse_get_map_value(response, expected_key="active", expected_value="none")


from types import SimpleNamespace

from scripts.local_docker_router_live_smoke import wait_for_runtime_api_show_info


class SequenceRuntimeClient:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def execute(self, command):
        self.calls += 1
        return self.results.pop(0)


def test_runtime_api_readiness_retries_only_transient_socket_startup(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "scripts.local_docker_router_live_smoke.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    transient = SimpleNamespace(
        status="failed",
        detail='socat: connect("/run/haproxy/admin.sock"): No such file or directory',
    )
    ready = SimpleNamespace(status="succeeded", detail="")
    client = SequenceRuntimeClient(transient, transient, ready)

    result = wait_for_runtime_api_show_info(client, attempts=5, interval_seconds=0.1)

    assert result.status == "succeeded"
    assert client.calls == 3
    assert sleeps == [0.1, 0.1]


def test_runtime_api_readiness_does_not_retry_non_transient_failures(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "scripts.local_docker_router_live_smoke.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    denied = SimpleNamespace(status="failed", detail="permission denied")
    client = SequenceRuntimeClient(denied)

    result = wait_for_runtime_api_show_info(client)

    assert result is denied
    assert client.calls == 1
    assert sleeps == []


def test_runtime_api_readiness_has_a_bounded_retry_window(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "scripts.local_docker_router_live_smoke.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    transient = SimpleNamespace(status="failed", detail="Connection refused")
    client = SequenceRuntimeClient(*([transient] * 3))

    result = wait_for_runtime_api_show_info(
        client, attempts=3, interval_seconds=0.2
    )

    assert result is transient
    assert client.calls == 3
    assert sleeps == [0.2, 0.2]


@pytest.mark.parametrize(
    "attempts,interval",
    [(0, 0.1), (81, 0.1), (True, 0.1), (3, 0), (3, 1.1), (3, True)],
)
def test_runtime_api_readiness_rejects_invalid_bounds(attempts, interval):
    with pytest.raises(ValueError):
        wait_for_runtime_api_show_info(
            SequenceRuntimeClient(), attempts=attempts, interval_seconds=interval
        )
