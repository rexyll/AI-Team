"""Secure Host-owned filesystem state for a per-scope HAProxy Router.

Writes deterministic HAProxy config and active-slot map files with private
permissions and crash-safe single-file replacement. No Docker or Runtime API I/O.
"""
from __future__ import annotations
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from runtime.deployment_traffic_router import TrafficPortBinding, TrafficRouterScope
from runtime.local_docker_router_config import render_active_slot_map, render_haproxy_router_config
from runtime.haproxy_runtime_readback import parse_show_servers_state
from runtime.local_docker_router_network import build_router_network_spec

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
RouterSlotValue = Literal["slot_a", "slot_b"]
RouterStateStatus = Literal["persisted", "unsupported", "failed"]

_SERVER_STATE_HEADER = (
    "1\n"
    "# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state "
    "srv_uweight srv_iweight srv_time_since_last_change srv_check_status "
    "srv_check_result srv_check_health srv_check_state srv_agent_state "
    "bk_f_forced_id srv_f_forced_id srv_fqdn srv_port srvrecord srv_use_ssl "
    "srv_check_port srv_check_addr srv_agent_addr srv_agent_port\n"
)

@dataclass(frozen=True)
class RouterStateRecord:
    network_name: str
    scope_fingerprint: str
    directory: str
    config_path: str
    active_slot_map_path: str
    config_sha256: str
    active_slot_map_sha256: str
    directory_mode: int
    file_mode: int
    server_state_sha256: str | None = None

    @property
    def server_state_path(self) -> str:
        return str(Path(self.directory) / "servers-state")

    def __post_init__(self) -> None:
        if self.directory_mode != _DIRECTORY_MODE or self.file_mode != _FILE_MODE:
            raise ValueError("Router state permissions must be directory 0700 and files 0600")
        for name, value in (
            ("config_sha256", self.config_sha256),
            ("active_slot_map_sha256", self.active_slot_map_sha256),
        ):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if self.server_state_sha256 is not None and (
            len(self.server_state_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.server_state_sha256)
        ):
            raise ValueError("server_state_sha256 must be a lowercase SHA-256 digest when provided")

@dataclass(frozen=True)
class RouterStateResult:
    status: RouterStateStatus
    record: RouterStateRecord | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"persisted", "unsupported", "failed"}:
            raise ValueError("invalid Router state result status")
        if self.status == "persisted" and not isinstance(self.record, RouterStateRecord):
            raise ValueError("persisted Router state requires a verified record")
        if self.status != "persisted" and self.record is not None:
            raise ValueError("unverified Router state must not expose trusted paths")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")

class LocalDockerRouterStateStore:
    """Persist one scope config and selector before Router container creation."""

    def __init__(self, state_root: str | Path) -> None:
        if not isinstance(state_root, (str, Path)) or not str(state_root).strip():
            raise TypeError("state_root must be a non-empty filesystem path")
        root = Path(state_root).expanduser()
        if not root.is_absolute():
            raise ValueError("state_root must be an absolute path")
        self.state_root = root

    @staticmethod
    def _check_no_symlink_components(path: Path) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise OSError(f"Router state path must not contain symlinks: {current}")

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise OSError("Router state path is not a real directory")
        if info.st_uid != os.geteuid():
            raise OSError("Router state directory must be owned by the current user")
        if stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE:
            os.chmod(path, _DIRECTORY_MODE)
        final = path.lstat()
        if stat.S_IMODE(final.st_mode) != _DIRECTORY_MODE or final.st_uid != os.geteuid():
            raise OSError("Router state directory permissions or ownership are unsafe")

    @staticmethod
    def _validate_existing_file(path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise OSError("Router state file must be a regular non-symlink file")
        if info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise OSError("Router state file ownership or link count is unsafe")
        if stat.S_IMODE(info.st_mode) != _FILE_MODE:
            os.chmod(path, _FILE_MODE)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        LocalDockerRouterStateStore._validate_existing_file(path)
        encoded = content.encode("utf-8")
        temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.tmp"
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, _FILE_MODE)
            os.fchmod(descriptor, _FILE_MODE)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            LocalDockerRouterStateStore._validate_existing_file(path)
            if stat.S_IMODE(path.lstat().st_mode) != _FILE_MODE:
                raise OSError("Router state file mode is not 0600 after atomic replacement")
            read_fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(read_fd, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            finally:
                os.close(read_fd)
            if b"".join(chunks) != encoded:
                raise OSError("Router state file read-back did not match persisted content")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def persist_servers_state(
        self,
        record: RouterStateRecord,
        port_bindings: tuple[TrafficPortBinding, ...],
        content: str,
    ) -> RouterStateResult:
        """Atomically persist a complete HAProxy show-servers-state snapshot.

        The snapshot must contain exactly both slots for every declared TCP
        backend. The Router bind-mounts the state directory read-only; atomic
        replacement of this file is visible to a later Router process restart.
        """
        if os.name != "posix" or not hasattr(os, "geteuid") or not hasattr(os, "fchmod"):
            return RouterStateResult("unsupported", detail="Private Router state storage requires POSIX filesystem semantics")
        try:
            if not isinstance(record, RouterStateRecord):
                raise TypeError("record must be a RouterStateRecord")
            if not isinstance(port_bindings, tuple) or not port_bindings or any(
                not isinstance(item, TrafficPortBinding) for item in port_bindings
            ):
                raise ValueError("port_bindings must be a non-empty tuple of TCP bindings")
            rows = parse_show_servers_state(content)
            expected = {
                (f"be_p{binding.host_port}", server)
                for binding in port_bindings
                for server in ("slot_a", "slot_b")
            }
            observed = {(row.backend, row.server) for row in rows}
            if observed != expected:
                raise ValueError("server-state snapshot does not contain exactly both slots for every Router backend")
            directory = Path(record.directory)
            self._check_no_symlink_components(directory)
            self._ensure_private_directory(directory)
            if directory.name != record.network_name:
                raise ValueError("server-state directory does not match its recorded scope name")
            server_state_path = directory / "servers-state"
            self._atomic_write(server_state_path, content)
            updated = RouterStateRecord(
                network_name=record.network_name,
                scope_fingerprint=record.scope_fingerprint,
                directory=record.directory,
                config_path=record.config_path,
                active_slot_map_path=record.active_slot_map_path,
                config_sha256=record.config_sha256,
                active_slot_map_sha256=record.active_slot_map_sha256,
                directory_mode=record.directory_mode,
                file_mode=record.file_mode,
                server_state_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            return RouterStateResult("persisted", updated)
        except (OSError, TypeError, ValueError) as exc:
            return RouterStateResult("failed", detail=f"{type(exc).__name__}: {exc}"[:1000])

    def persist(self, scope: TrafficRouterScope, port_bindings: tuple[TrafficPortBinding, ...], *, active_slot: RouterSlotValue | None = None) -> RouterStateResult:
        """Persist bootstrap files; call before creating Router, not during live routing.

        Later selector changes must use Runtime API plus read-back; replacing the
        map file alone never changes HAProxy in-memory routing.
        """
        if os.name != "posix" or not hasattr(os, "geteuid") or not hasattr(os, "fchmod"):
            return RouterStateResult("unsupported", detail="Private Router state storage requires POSIX filesystem semantics")
        try:
            spec = build_router_network_spec(scope)
            config = render_haproxy_router_config(port_bindings)
            active_map = render_active_slot_map(active_slot)
            self._check_no_symlink_components(self.state_root)
            self._ensure_private_directory(self.state_root)
            scope_dir = self.state_root / spec.network_name
            self._check_no_symlink_components(scope_dir)
            self._ensure_private_directory(scope_dir)
            config_path = scope_dir / "haproxy.cfg"
            map_path = scope_dir / "active-slot.map"
            server_state_path = scope_dir / "servers-state"
            self._atomic_write(config_path, config)
            self._atomic_write(map_path, active_map)
            self._atomic_write(server_state_path, _SERVER_STATE_HEADER)
            record = RouterStateRecord(
                network_name=spec.network_name, scope_fingerprint=spec.scope_fingerprint,
                directory=str(scope_dir), config_path=str(config_path),
                active_slot_map_path=str(map_path),
                config_sha256=hashlib.sha256(config.encode("utf-8")).hexdigest(),
                active_slot_map_sha256=hashlib.sha256(active_map.encode("utf-8")).hexdigest(),
                directory_mode=_DIRECTORY_MODE, file_mode=_FILE_MODE,
                server_state_sha256=hashlib.sha256(_SERVER_STATE_HEADER.encode("utf-8")).hexdigest(),
            )
            return RouterStateResult("persisted", record)
        except (OSError, TypeError, ValueError) as exc:
            return RouterStateResult("failed", detail=f"{type(exc).__name__}: {exc}"[:1000])
