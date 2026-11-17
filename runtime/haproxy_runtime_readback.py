"""Strict, header-driven HAProxy Runtime API server read-back parsing.

No Docker or Runtime API I/O is performed here. Any format ambiguity,
missing row, endpoint mismatch, or non-UP state is rejected.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import re
from dataclasses import dataclass
from typing import Literal

_BACKEND_SERVER = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_REQUIRED_STATE_COLUMNS = frozenset({
    "be_name", "srv_name", "srv_addr", "srv_op_state",
    "srv_admin_state", "srv_check_result", "srv_check_state", "srv_port",
})
_REQUIRED_STAT_COLUMNS = frozenset({"pxname", "svname", "status", "scur"})


@dataclass(frozen=True)
class ExpectedHAProxyServer:
    backend: str
    server: str
    address: str
    port: int

    def __post_init__(self) -> None:
        for name in ("backend", "server"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _BACKEND_SERVER.fullmatch(value):
                raise ValueError(f"{name} must be a safe lowercase HAProxy identifier")
        try:
            parsed = ipaddress.ip_address(self.address)
        except (TypeError, ValueError) as exc:
            raise ValueError("address must be a literal IP address") from exc
        if str(parsed) != self.address:
            raise ValueError("address must use canonical IP notation")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer in the range 1..65535")


@dataclass(frozen=True)
class HAProxyServerStateRow:
    backend: str
    server: str
    address: str
    port: int
    operational_state: int
    administrative_state: int
    check_result: int
    check_state: int

    @property
    def fully_up_and_enabled(self) -> bool:
        # HAProxy 3.4: SRV_ST_RUNNING=2, CHK_RES_PASSED=3,
        # CHK_ST_CONFIGURED=0x02, CHK_ST_ENABLED=0x04.
        return (
            self.operational_state == 2
            and self.administrative_state == 0
            and self.check_result == 3
            and (self.check_state & 0x06) == 0x06
        )


@dataclass(frozen=True)
class HAProxyServerStatRow:
    backend: str
    server: str
    status: str
    current_sessions: int


@dataclass(frozen=True)
class HAProxySlotServerObservation:
    backend: str
    server: str
    address: str
    port: int
    operational_state: int
    administrative_state: int
    check_result: int
    check_state: int
    status: str
    current_sessions: int


@dataclass(frozen=True)
class HAProxySlotReadbackResult:
    status: Literal["verified", "mismatch", "invalid_response"]
    observations: tuple[HAProxySlotServerObservation, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"verified", "mismatch", "invalid_response"}:
            raise ValueError("invalid slot read-back status")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, HAProxySlotServerObservation) for item in self.observations
        ):
            raise TypeError("observations must be a tuple of HAProxySlotServerObservation")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")
        if self.status == "verified" and self.detail:
            raise ValueError("verified slot read-back must not contain failure detail")
        if self.status != "verified" and not self.detail:
            raise ValueError("unverified slot read-back requires failure detail")


def _integer(value: str, name: str, maximum: int) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty integer field")
    try:
        parsed = int(value, 0) if value.lower().startswith("0x") else int(value, 10)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer field") from exc
    if not 0 <= parsed <= maximum:
        raise ValueError(f"{name} is outside its allowed range")
    return parsed


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _BACKEND_SERVER.fullmatch(value):
        raise ValueError(f"{name} is not a safe HAProxy identifier")
    return value


def parse_show_servers_state(response: str) -> tuple[HAProxyServerStateRow, ...]:
    """Parse version-1 show servers state output by column name."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("show servers state returned an empty response")
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if len(lines) < 3 or lines[0] != "1":
        raise ValueError("show servers state format version must be 1 with at least one data row")
    if not lines[1].startswith("#"):
        raise ValueError("show servers state omitted its column header")
    columns = lines[1][1:].strip().split()
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("show servers state has an empty or duplicate column header")
    missing = _REQUIRED_STATE_COLUMNS.difference(columns)
    if missing:
        raise ValueError("show servers state is missing required columns: " + ", ".join(sorted(missing)))
    positions = {name: columns.index(name) for name in _REQUIRED_STATE_COLUMNS}
    rows: list[HAProxyServerStateRow] = []
    seen: set[tuple[str, str]] = set()
    for line in lines[2:]:
        if line.startswith("#"):
            continue
        values = line.split()
        if len(values) != len(columns):
            raise ValueError("show servers state row width does not match its header")
        backend = _identifier(values[positions["be_name"]], "backend")
        server = _identifier(values[positions["srv_name"]], "server")
        key = (backend, server)
        if key in seen:
            raise ValueError("show servers state contains a duplicate backend/server row")
        seen.add(key)
        try:
            address = str(ipaddress.ip_address(values[positions["srv_addr"]]))
        except ValueError as exc:
            raise ValueError("show servers state contains an invalid server address") from exc
        port = _integer(values[positions["srv_port"]], "srv_port", 65535)
        if port == 0:
            raise ValueError("show servers state server port must be non-zero")
        rows.append(HAProxyServerStateRow(
            backend, server, address, port,
            _integer(values[positions["srv_op_state"]], "srv_op_state", 3),
            _integer(values[positions["srv_admin_state"]], "srv_admin_state", 0x7F),
            _integer(values[positions["srv_check_result"]], "srv_check_result", 4),
            _integer(values[positions["srv_check_state"]], "srv_check_state", 0x1F),
        ))
    if not rows:
        raise ValueError("show servers state returned no server rows")
    return tuple(rows)


def parse_show_stat_servers(response: str) -> tuple[HAProxyServerStatRow, ...]:
    """Parse HAProxy CSV statistics and retain concrete server rows."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("show stat returned an empty response")
    try:
        records = list(csv.reader(io.StringIO(response, newline=""), strict=True))
    except csv.Error as exc:
        raise ValueError("show stat returned malformed CSV") from exc
    records = [record for record in records if record and any(cell.strip() for cell in record)]
    if len(records) < 2:
        raise ValueError("show stat must contain a header and at least one server row")
    header = list(records[0])
    header[0] = header[0].lstrip("#").strip()
    header = [item.strip() for item in header]
    if not header or len(header) != len(set(header)):
        raise ValueError("show stat has an empty or duplicate CSV header")
    missing = _REQUIRED_STAT_COLUMNS.difference(header)
    if missing:
        raise ValueError("show stat is missing required columns: " + ", ".join(sorted(missing)))
    positions = {name: header.index(name) for name in _REQUIRED_STAT_COLUMNS}
    rows: list[HAProxyServerStatRow] = []
    seen: set[tuple[str, str]] = set()
    for record in records[1:]:
        if record[0].lstrip().startswith("#"):
            continue
        if len(record) != len(header):
            raise ValueError("show stat CSV row width does not match its header")
        backend = _identifier(record[positions["pxname"]].strip(), "backend")
        server = record[positions["svname"]].strip()
        if server in {"BACKEND", "FRONTEND"}:
            continue
        server = _identifier(server, "server")
        key = (backend, server)
        if key in seen:
            raise ValueError("show stat contains a duplicate backend/server row")
        seen.add(key)
        status = record[positions["status"]].strip()
        if not status:
            raise ValueError("show stat server status is empty")
        rows.append(HAProxyServerStatRow(
            backend, server, status,
            _integer(record[positions["scur"]].strip(), "scur", 2**31 - 1),
        ))
    if not rows:
        raise ValueError("show stat returned no concrete server rows")
    return tuple(rows)


def verify_inactive_slot_readback(
    expected: tuple[ExpectedHAProxyServer, ...],
    *,
    servers_state_response: str,
    stat_response: str,
) -> HAProxySlotReadbackResult:
    """Verify exact server endpoints, UP/check state, and current-session counters."""
    if not isinstance(expected, tuple) or not expected:
        raise ValueError("expected must be a non-empty tuple")
    if any(not isinstance(item, ExpectedHAProxyServer) for item in expected):
        raise TypeError("expected must contain ExpectedHAProxyServer values")
    keys = [(item.backend, item.server) for item in expected]
    if len(keys) != len(set(keys)):
        raise ValueError("expected backend/server pairs must be unique")
    try:
        state_rows = parse_show_servers_state(servers_state_response)
        stat_rows = parse_show_stat_servers(stat_response)
    except (TypeError, ValueError) as exc:
        return HAProxySlotReadbackResult("invalid_response", detail=str(exc))
    states = {(row.backend, row.server): row for row in state_rows}
    stats = {(row.backend, row.server): row for row in stat_rows}
    observations: list[HAProxySlotServerObservation] = []
    for item in expected:
        key = (item.backend, item.server)
        state = states.get(key)
        stat = stats.get(key)
        if state is None or stat is None:
            return HAProxySlotReadbackResult(
                "mismatch", tuple(observations),
                f"HAProxy read-back omitted backend/server {item.backend}/{item.server}",
            )
        if state.address != item.address or state.port != item.port:
            return HAProxySlotReadbackResult(
                "mismatch", tuple(observations),
                f"HAProxy server address/port mismatch for {item.backend}/{item.server}",
            )
        observation = HAProxySlotServerObservation(
            item.backend, item.server, state.address, state.port,
            state.operational_state, state.administrative_state,
            state.check_result, state.check_state, stat.status, stat.current_sessions,
        )
        observations.append(observation)
        if not state.fully_up_and_enabled or stat.status != "UP":
            return HAProxySlotReadbackResult(
                "mismatch", tuple(observations),
                f"HAProxy backend/server is not fully UP and enabled: {item.backend}/{item.server}",
            )
    return HAProxySlotReadbackResult("verified", tuple(observations))
