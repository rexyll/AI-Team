"""Isolated per-task developer workspaces with deterministic three-way merge.

Every developer task runs against its own copy of the project workspace, so
concurrent developers can never touch the same live files. The copy is taken
from the current main workspace when the task starts; when the task completes,
only the files that actually changed are merged back, and a change to the same
path by the main workspace in the meantime is a loud conflict, not a silent
overwrite. Failed work is discarded whole.

The manager is a file-level branch/merge boundary. It holds no LLM behavior
and every rule here is deterministic and unit-testable.
"""
from __future__ import annotations

import hashlib
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path


# Directories that carry no product meaning: tool/cache noise is neither
# copied into a lease nor merged back, so cache churn can never create
# phantom conflicts. The context archive IS copied (read-only reference for
# developers); lease merges ignore it because a lease never writes there.
SKIP_DIRECTORY_NAMES = frozenset({
    "__pycache__", ".pytest_cache", ".dev-workspaces",
    ".git", ".idea", ".vscode", ".mypy_cache", ".ruff_cache",
})


class WorkspaceMergeConflict(RuntimeError):
    """A lease and the main workspace changed the same path concurrently."""


@dataclass(frozen=True)
class WorkspaceLease:
    task_id: str
    root: Path
    base_hashes: dict[str, str]


@dataclass(frozen=True)
class MergeReport:
    task_id: str
    changed: tuple[str, ...] = field(default_factory=tuple)
    added: tuple[str, ...] = field(default_factory=tuple)
    deleted: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "changed": list(self.changed),
            "added": list(self.added),
            "deleted": list(self.deleted),
        }


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not root.exists():
        return hashes
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRECTORY_NAMES for part in relative.parts):
            continue
        hashes[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class DeveloperWorkspaceManager:
    """Own the issue/merge/discard lifecycle of per-task workspace copies."""

    WORKSPACE_DIRNAME = ".dev-workspaces"

    def __init__(self, main_root: str | Path) -> None:
        self.main_root = Path(main_root).resolve()
        self._root = self.main_root / self.WORKSPACE_DIRNAME
        self._lock = threading.Lock()

    def issue(self, task_id: str) -> WorkspaceLease:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            lease_root = self._root / task_id
            if lease_root.exists():
                # A prior round of this task crashed before finalizing; the
                # partial copy is stale state, not reusable history.
                shutil.rmtree(lease_root)
            lease_root.mkdir(parents=True)
            self._copy_tree(self.main_root, lease_root)
            return WorkspaceLease(
                task_id=task_id,
                root=lease_root,
                base_hashes=_tree_hashes(lease_root),
            )

    def merge(self, lease: WorkspaceLease) -> MergeReport:
        """Merge the lease's diff back; refuse cross-writes loudly."""
        if not isinstance(lease, WorkspaceLease):
            raise TypeError("lease must be a WorkspaceLease")
        with self._lock:
            final_hashes = _tree_hashes(lease.root)
            main_hashes = _tree_hashes(self.main_root)

            base = lease.base_hashes
            conflict = sorted(
                path
                for path in set(final_hashes) & set(main_hashes)
                if path in base
                and final_hashes[path] != base[path]
                and main_hashes[path] != base[path]
            )
            if conflict:
                raise WorkspaceMergeConflict(
                    f"workspace merge conflict for task {lease.task_id}; "
                    "the following paths were modified concurrently: "
                    + ", ".join(conflict)
                )

            changed: list[str] = []
            added: list[str] = []
            for path, digest in sorted(final_hashes.items()):
                if path in base and base[path] == digest:
                    continue
                destination = self.main_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(lease.root / path, destination)
                if path in base:
                    changed.append(path)
                else:
                    added.append(path)

            deleted: list[str] = []
            for path in sorted(set(base) - set(final_hashes)):
                main_current = main_hashes.get(path)
                if main_current is not None and main_current != base[path]:
                    raise WorkspaceMergeConflict(
                        f"workspace merge conflict for task {lease.task_id}; "
                        f"path {path} was deleted locally but modified concurrently"
                    )
                (self.main_root / path).unlink(missing_ok=True)
                deleted.append(path)

            return MergeReport(
                task_id=lease.task_id,
                changed=tuple(changed),
                added=tuple(added),
                deleted=tuple(deleted),
            )

    def discard(self, lease: WorkspaceLease) -> None:
        if not isinstance(lease, WorkspaceLease):
            raise TypeError("lease must be a WorkspaceLease")
        with self._lock:
            if lease.root.exists():
                shutil.rmtree(lease.root)

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        if not source.exists():
            return
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if any(part in SKIP_DIRECTORY_NAMES for part in relative.parts):
                continue
            target = destination / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file() and not path.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
