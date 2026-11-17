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


RouterStateLoadStatus = Literal["loaded", "unsupported", "failed"]


@dataclass(frozen=True)
class RouterStateLoadResult:
    """Read-only result for reloading state against a durable Host metadata record."""

    status: RouterStateLoadStatus
    record: RouterStateRecord | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"loaded", "unsupported", "failed"}:
            raise ValueError("invalid Router state load status")
        if self.status == "loaded" and not isinstance(self.record, RouterStateRecord):
            raise ValueError("loaded Router state requires a verified record")
        if self.status != "loaded" and self.record is not None:
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

    def persist_active_slot_map(
        self,
        record: RouterStateRecord,
        *,
        expected_active_slot: RouterSlotValue | None,
        active_slot: RouterSlotValue | None,
    ) -> RouterStateResult:
        """Atomically update the restart selector after checking its prior value.

        Runtime API memory remains authoritative for live traffic. This method
        changes only the Host-owned restart file and returns a new digest-bound
        record after secure read-back.
        """
        if os.name != "posix" or not hasattr(os, "geteuid") or not hasattr(os, "fchmod"):
            return RouterStateResult(
                "unsupported",
                detail="Private Router state storage requires POSIX filesystem semantics",
            )
        try:
            if not isinstance(record, RouterStateRecord):
                raise TypeError("record must be a RouterStateRecord")
            if expected_active_slot not in {None, "slot_a", "slot_b"}:
                raise ValueError("expected_active_slot must be slot_a, slot_b, or None")
            if active_slot not in {None, "slot_a", "slot_b"}:
                raise ValueError("active_slot must be slot_a, slot_b, or None")
            if active_slot == expected_active_slot:
                raise ValueError("active-slot persistence must change the selector")
            directory = Path(record.directory)
            self._check_no_symlink_components(directory)
            directory_info = directory.lstat()
            if (
                not stat.S_ISDIR(directory_info.st_mode)
                or stat.S_ISLNK(directory_info.st_mode)
                or directory_info.st_uid != os.geteuid()
                or stat.S_IMODE(directory_info.st_mode) != _DIRECTORY_MODE
                or directory.name != record.network_name
            ):
                raise OSError("Router state directory identity, ownership, or mode is unsafe")
            map_path = Path(record.active_slot_map_path)
            if map_path != directory / "active-slot.map":
                raise ValueError("active-slot map path does not match the recorded scope directory")

            def read_private_file(path: Path, expected_digest: str | None) -> bytes:
                info = path.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or info.st_uid != directory_info.st_uid
                    or info.st_gid != directory_info.st_gid
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != _FILE_MODE
                ):
                    raise OSError("Router state file ownership, type, link count, or mode is unsafe")
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    opened = os.fstat(descriptor)
                    if (
                        opened.st_dev != info.st_dev
                        or opened.st_ino != info.st_ino
                        or not stat.S_ISREG(opened.st_mode)
                        or opened.st_uid != directory_info.st_uid
                        or opened.st_gid != directory_info.st_gid
                        or opened.st_nlink != 1
                        or stat.S_IMODE(opened.st_mode) != _FILE_MODE
                    ):
                        raise OSError("Router state file changed during secure open")
                    chunks: list[bytes] = []
                    while True:
                        chunk = os.read(descriptor, 65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                finally:
                    os.close(descriptor)
                payload = b"".join(chunks)
                if expected_digest is None or hashlib.sha256(payload).hexdigest() != expected_digest:
                    raise OSError(f"Router state file digest mismatch: {path.name}")
                return payload

            read_private_file(Path(record.config_path), record.config_sha256)
            current_map = read_private_file(map_path, record.active_slot_map_sha256)
            read_private_file(Path(record.server_state_path), record.server_state_sha256)
            expected_content = render_active_slot_map(expected_active_slot).encode("utf-8")
            if current_map != expected_content:
                raise OSError("Host active-slot map does not match the expected prior selector")
            next_content = render_active_slot_map(active_slot)
            self._atomic_write(map_path, next_content)
            updated_digest = hashlib.sha256(next_content.encode("utf-8")).hexdigest()
            written = read_private_file(map_path, updated_digest)
            if written != next_content.encode("utf-8"):
                raise OSError("Host active-slot map read-back differs from the requested selector")
            updated = RouterStateRecord(
                network_name=record.network_name,
                scope_fingerprint=record.scope_fingerprint,
                directory=record.directory,
                config_path=record.config_path,
                active_slot_map_path=record.active_slot_map_path,
                config_sha256=record.config_sha256,
                active_slot_map_sha256=updated_digest,
                directory_mode=record.directory_mode,
                file_mode=record.file_mode,
                server_state_sha256=record.server_state_sha256,
            )
            return RouterStateResult("persisted", updated)
        except (OSError, TypeError, ValueError) as exc:
            return RouterStateResult(
                "failed",
                detail=f"{type(exc).__name__}: {exc}"[:1000],
            )

    def load(
        self,
        scope: TrafficRouterScope,
        port_bindings: tuple[TrafficPortBinding, ...],
        *,
        expected_record: RouterStateRecord,
    ) -> RouterStateLoadResult:
        """Read and verify existing Host Router state without rewriting it.

        The expected record must come from a separate durable Host metadata
        store (for example the deployment-history database). Files on disk are
        not allowed to self-authorize their own digest after process restart.
        This method never calls persist() and never resets the active selector.
        """
        if os.name != "posix" or not hasattr(os, "geteuid"):
            return RouterStateLoadResult(
                "unsupported",
                detail="Private Router state reload requires POSIX filesystem semantics",
            )
        try:
            if not isinstance(scope, TrafficRouterScope):
                raise TypeError("scope must be a TrafficRouterScope")
            if not isinstance(port_bindings, tuple) or not port_bindings or any(
                not isinstance(item, TrafficPortBinding) for item in port_bindings
            ):
                raise ValueError("port_bindings must be a non-empty tuple of TCP bindings")
            if not isinstance(expected_record, RouterStateRecord):
                raise TypeError("expected_record must be a RouterStateRecord")

            network = build_router_network_spec(scope)
            directory = self.state_root / network.network_name
            config_path = directory / "haproxy.cfg"
            map_path = directory / "active-slot.map"
            server_state_path = directory / "servers-state"
            if (
                expected_record.network_name != network.network_name
                or expected_record.scope_fingerprint != network.scope_fingerprint
                or Path(expected_record.directory) != directory
                or Path(expected_record.config_path) != config_path
                or Path(expected_record.active_slot_map_path) != map_path
                or expected_record.directory_mode != _DIRECTORY_MODE
                or expected_record.file_mode != _FILE_MODE
                or expected_record.server_state_sha256 is None
            ):
                raise ValueError("durable Router state record does not match the requested scope and bindings")

            self._check_no_symlink_components(self.state_root)
            self._check_no_symlink_components(directory)
            directory_info = directory.lstat()
            if (
                not stat.S_ISDIR(directory_info.st_mode)
                or stat.S_ISLNK(directory_info.st_mode)
                or directory_info.st_uid != os.geteuid()
                or stat.S_IMODE(directory_info.st_mode) != _DIRECTORY_MODE
            ):
                raise OSError("Router state directory ownership, type, or mode is unsafe")

            def read_private_file(path: Path, expected_digest: str) -> bytes:
                info = path.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or info.st_uid != directory_info.st_uid
                    or info.st_gid != directory_info.st_gid
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != _FILE_MODE
                ):
                    raise OSError(f"Router state file ownership, type, link count, or mode is unsafe: {path.name}")
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    opened = os.fstat(descriptor)
                    if (
                        opened.st_dev != info.st_dev
                        or opened.st_ino != info.st_ino
                        or not stat.S_ISREG(opened.st_mode)
                        or opened.st_uid != directory_info.st_uid
                        or opened.st_gid != directory_info.st_gid
                        or opened.st_nlink != 1
                        or stat.S_IMODE(opened.st_mode) != _FILE_MODE
                        or opened.st_size > 2_000_000
                    ):
                        raise OSError(f"Router state file changed during secure open: {path.name}")
                    chunks: list[bytes] = []
                    total = 0
                    while True:
                        chunk = os.read(descriptor, min(65536, 2_000_001 - total))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 2_000_000:
                            raise OSError(f"Router state file exceeds the reload size limit: {path.name}")
                        chunks.append(chunk)
                finally:
                    os.close(descriptor)
                payload = b"".join(chunks)
                if hashlib.sha256(payload).hexdigest() != expected_digest:
                    raise OSError(f"Router state file digest mismatch: {path.name}")
                return payload

            config_bytes = read_private_file(config_path, expected_record.config_sha256)
            map_bytes = read_private_file(map_path, expected_record.active_slot_map_sha256)
            server_state_bytes = read_private_file(
                server_state_path, expected_record.server_state_sha256
            )

            expected_config = render_haproxy_router_config(port_bindings).encode("utf-8")
            if config_bytes != expected_config:
                raise ValueError("persisted HAProxy config does not match the deterministic scope configuration")

            allowed_maps = {
                render_active_slot_map(None).encode("utf-8"): None,
                render_active_slot_map("slot_a").encode("utf-8"): "slot_a",
                render_active_slot_map("slot_b").encode("utf-8"): "slot_b",
            }
            active_slot = allowed_maps.get(map_bytes, "invalid")
            if active_slot == "invalid":
                raise ValueError("persisted active-slot map is not one exact allowlisted selector")

            if server_state_bytes == _SERVER_STATE_HEADER.encode("utf-8"):
                if active_slot is not None:
                    raise ValueError("active Router selector cannot load from an empty server-state snapshot")
            else:
                rows = parse_show_servers_state(server_state_bytes.decode("utf-8"))
                expected_rows = {
                    (f"be_p{binding.host_port}", server)
                    for binding in port_bindings
                    for server in ("slot_a", "slot_b")
                }
                observed_rows = {(row.backend, row.server) for row in rows}
                if observed_rows != expected_rows:
                    raise ValueError("persisted server-state snapshot does not contain exactly both slots for every backend")
                if active_slot is not None:
                    active_rows = tuple(row for row in rows if row.server == active_slot)
                    if len(active_rows) != len(port_bindings) or any(
                        row.address is None for row in active_rows
                    ):
                        raise ValueError(
                            "active Router selector cannot load from unresolved server endpoints"
                        )

            return RouterStateLoadResult("loaded", expected_record)
        except (OSError, TypeError, ValueError, UnicodeDecodeError) as exc:
            return RouterStateLoadResult(
                "failed",
                detail=f"{type(exc).__name__}: {str(exc)[:900]}",
            )

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
