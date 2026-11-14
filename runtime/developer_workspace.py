"""Isolated per-task developer workspaces with conflict-safe file merging.

A lease is a private copy of one deliverable root. A successful Developer
attempt may merge its file-level delta back only when no other task changed
the same path since the lease was issued. Failed attempts are discarded.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4


SKIP_DIRECTORIES = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "node_modules", ".ai-team-workspaces",
})
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class WorkspaceMergeConflict(RuntimeError):
    """A task lease and the canonical workspace changed the same path."""


@dataclass(frozen=True)
class WorkspaceLease:
    task_id: str
    root: Path
    base_hashes: dict[str, str]


@dataclass(frozen=True)
class MergeReport:
    task_id: str
    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "changed": list(self.changed),
            "added": list(self.added),
            "deleted": list(self.deleted),
        }


def _relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe workspace-relative path: {value!r}")
    return Path(*path.parts)


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not root.exists():
        return hashes
    for current, directories, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in SKIP_DIRECTORIES and not (base / name).is_symlink()
        )
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _contains_symlink(root: Path) -> bool:
    if not root.exists():
        return False
    for current, directories, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        if any((base / name).is_symlink() for name in directories):
            return True
        if any((base / name).is_symlink() for name in filenames):
            return True
        directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES]
    return False


class DeveloperWorkspaceManager:
    """Issue isolated task workspaces and merge only conflict-free deltas."""

    def __init__(self, main_root: str | Path) -> None:
        self.main_root = Path(main_root).resolve()
        self._lease_parent = self.main_root.parent / ".ai-team-dev-workspaces"
        self._lock = threading.RLock()
        self.main_root.mkdir(parents=True, exist_ok=True)

    def issue(self, task_id: str) -> WorkspaceLease:
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or task_id in {".", ".."}:
            raise ValueError("task_id must be a safe non-empty identifier")
        with self._lock:
            self._lease_parent.mkdir(parents=True, exist_ok=True)
            lease_root = self._lease_parent / f"{task_id}-{uuid4().hex}"
            lease_root.mkdir(parents=False, exist_ok=False)
            self._copy_tree(self.main_root, lease_root)
            return WorkspaceLease(task_id, lease_root, _tree_hashes(lease_root))

    def merge(self, lease: WorkspaceLease) -> MergeReport:
        if not isinstance(lease, WorkspaceLease):
            raise TypeError("lease must be a WorkspaceLease")
        with self._lock:
            if not lease.root.is_dir() or lease.root.parent != self._lease_parent:
                raise ValueError("lease root is not owned by this workspace manager")
            if _contains_symlink(lease.root):
                raise ValueError("symbolic links are not allowed in a developer workspace")
            local = _tree_hashes(lease.root)
            canonical = _tree_hashes(self.main_root)
            base = lease.base_hashes

            conflicts: list[str] = []
            for name in sorted(set(base) | set(local)):
                path = _relative_path(name)
                base_hash = base.get(name)
                local_hash = local.get(name)
                canonical_hash = canonical.get(name)
                local_changed = local_hash != base_hash
                canonical_changed = canonical_hash != base_hash
                if local_changed and canonical_changed and local_hash != canonical_hash:
                    conflicts.append(name)
            if conflicts:
                raise WorkspaceMergeConflict(
                    f"workspace merge conflict for task {lease.task_id}: "
                    + ", ".join(conflicts)
                )

            changed: list[str] = []
            added: list[str] = []
            deleted: list[str] = []
            for name in sorted(local):
                path = _relative_path(name)
                digest = local[name]
                if base.get(name) == digest:
                    continue
                destination = self.main_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = lease.root / path
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=f".{destination.name}.",
                    suffix=".merge-tmp", delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                try:
                    shutil.copyfile(source, temporary_path)
                    shutil.copystat(source, temporary_path)
                    os.replace(temporary_path, destination)
                finally:
                    temporary_path.unlink(missing_ok=True)
                (changed if name in base else added).append(name)

            for name in sorted(set(base) - set(local)):
                path = _relative_path(name)
                destination = self.main_root / path
                if destination.exists() and destination.is_file():
                    destination.unlink()
                    deleted.append(name)

            return MergeReport(lease.task_id, tuple(changed), tuple(added), tuple(deleted))

    def discard(self, lease: WorkspaceLease) -> None:
        if not isinstance(lease, WorkspaceLease):
            raise TypeError("lease must be a WorkspaceLease")
        with self._lock:
            if lease.root.parent != self._lease_parent:
                raise ValueError("lease root is not owned by this workspace manager")
            shutil.rmtree(lease.root, ignore_errors=True)
            try:
                self._lease_parent.rmdir()
            except OSError:
                pass

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        for current, directories, filenames in os.walk(source, followlinks=False):
            base = Path(current)
            relative_base = base.relative_to(source)
            directories[:] = sorted(
                name for name in directories
                if name not in SKIP_DIRECTORIES and not (base / name).is_symlink()
            )
            for name in directories:
                (destination / relative_base / name).mkdir(parents=True, exist_ok=True)
            for name in sorted(filenames):
                source_file = base / name
                if source_file.is_symlink() or not source_file.is_file():
                    continue
                target = destination / relative_base / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target)
