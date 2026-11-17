from __future__ import annotations

import pytest

from scripts.local_docker_router_live_smoke import parse_get_map_value, parse_show_info


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


def test_parse_get_map_value_accepts_exact_active_none_entry():
    response = (
        'type=beg, case=sensitive, found=yes, idx=tree, '
        'key="active", value="none", type="str"\n'
    )
    assert parse_get_map_value(response, expected_key="active") == "none"


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
        parse_get_map_value(response, expected_key="active")
