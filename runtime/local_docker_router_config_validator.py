"""Validate generated HAProxy config against the pinned image on Docker Engine.

The validator mounts only Host-owned config and active-map files read-only, runs
HAProxy -c by immutable image ID with no network and no capabilities, and does
not create a persistent Router or bind a host port.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from runtime.local_docker_provider import LocalDockerProvider
from runtime.local_docker_router_image import DockerRouterImageIdentity
from runtime.local_docker_router_state import RouterStateRecord

_CONFIG_DESTINATION = "/usr/local/etc/haproxy/haproxy.cfg"
_MAP_DESTINATION = "/usr/local/etc/haproxy/active-slot.map"
_TMPFS_SPEC = "/run/haproxy:rw,noexec,nosuid,nodev,size=1m,mode=700"
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_EXPECTED_MAP = "active none\n"
ConfigValidationStatus = Literal["valid", "invalid_config", "invalid_state", "unavailable", "unsupported"]

@dataclass(frozen=True)
class RouterConfigValidationResult:
    status: ConfigValidationStatus
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"valid", "invalid_config", "invalid_state", "unavailable", "unsupported"}:
            raise ValueError("invalid Router config validation status")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")

class LocalDockerRouterConfigValidator:
    """Run haproxy -c against exact persisted files using a verified image ID."""

    def __init__(self, provider: LocalDockerProvider) -> None:
        if not isinstance(provider, LocalDockerProvider):
            raise TypeError("provider must be a LocalDockerProvider")
        self.provider = provider

    @staticmethod
    def _safe_path(path: Path) -> bool:
        value = str(path)
        if not path.is_absolute() or any(char in value for char in (",", "\x00", "\r", "\n")):
            return False
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                return False
        return True

    @classmethod
    def _validate_state(cls, state: RouterStateRecord) -> tuple[Path | None, Path | None, str | None]:
        if not isinstance(state, RouterStateRecord):
            return None, None, "state must be a RouterStateRecord"
        if os.name != "posix" or not hasattr(os, "geteuid"):
            return None, None, "unsupported: private Router state requires POSIX filesystem semantics"
        if state.directory_mode != _DIRECTORY_MODE or state.file_mode != _FILE_MODE:
            return None, None, "Router state record permissions must be 0700/0600"
        directory = Path(state.directory)
        config_path = Path(state.config_path)
        map_path = Path(state.active_slot_map_path)
        if not all(cls._safe_path(path) for path in (directory, config_path, map_path)):
            return None, None, "Router state paths must be absolute and contain no symlinks or Docker mount delimiters"
        if config_path.parent != directory or map_path.parent != directory:
            return None, None, "Router config/map files must be direct children of the scope directory"
        if config_path.name != "haproxy.cfg" or map_path.name != "active-slot.map":
            return None, None, "Router config/map filenames are not canonical"
        try:
            directory_info = directory.lstat()
            if not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode):
                return None, None, "Router state directory must be a real directory"
            if directory_info.st_uid != os.geteuid() or stat.S_IMODE(directory_info.st_mode) != _DIRECTORY_MODE:
                return None, None, "Router state directory owner/mode must be current user/0700"
            contents: dict[Path, bytes] = {}
            for path, expected_hash in ((config_path, state.config_sha256), (map_path, state.active_slot_map_sha256)):
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    return None, None, f"Router state file is not a regular non-symlink file: {path.name}"
                if info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != _FILE_MODE:
                    return None, None, f"Router state file owner/mode/link count is unsafe: {path.name}"
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected_hash:
                    return None, None, f"Router state file hash mismatch: {path.name}"
                contents[path] = raw
            if contents[map_path] != _EXPECTED_MAP.encode("utf-8"):
                return None, None, "Router startup map must be the fail-closed active none selector"
        except OSError as exc:
            return None, None, f"{type(exc).__name__}: {exc}"
        return config_path, map_path, None

    def validate(self, image: DockerRouterImageIdentity, state: RouterStateRecord) -> RouterConfigValidationResult:
        """Return valid only when pinned HAProxy accepts the exact Host files."""
        if not isinstance(image, DockerRouterImageIdentity):
            raise TypeError("image must be a DockerRouterImageIdentity")
        config_path, map_path, state_error = self._validate_state(state)
        if state_error:
            if state_error.startswith("unsupported:"):
                return RouterConfigValidationResult("unsupported", state_error)
            return RouterConfigValidationResult("invalid_state", state_error)
        assert config_path is not None and map_path is not None
        argv = [
            "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--tmpfs", _TMPFS_SPEC,
            "--mount", f"type=bind,src={config_path},dst={_CONFIG_DESTINATION},readonly",
            "--mount", f"type=bind,src={map_path},dst={_MAP_DESTINATION},readonly",
            "--entrypoint", "/usr/local/sbin/haproxy", image.image_id,
            "-c", "-f", _CONFIG_DESTINATION,
        ]
        result, error = self.provider._execute(argv)
        if error:
            if self.provider._is_unavailable(error) or "timed out" in error.lower() or "timeout" in error.lower():
                return RouterConfigValidationResult("unavailable", error[:1000])
            return RouterConfigValidationResult("invalid_config", error[:1000])
        assert result is not None
        if result.returncode == 0:
            detail = (result.stdout or "HAProxy configuration syntax is valid").strip()
            return RouterConfigValidationResult("valid", detail[-1000:])
        detail = (result.stderr or result.stdout or "HAProxy rejected the generated Router configuration").strip()
        if self.provider._is_unavailable(detail) or "timed out" in detail.lower() or "timeout" in detail.lower():
            return RouterConfigValidationResult("unavailable", detail[-1000:])
        return RouterConfigValidationResult("invalid_config", detail[-1000:])
