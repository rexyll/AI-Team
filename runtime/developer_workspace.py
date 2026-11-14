"""Isolated per-task developer workspaces with durable leases and safe merges.

Each lease is a private source snapshot. Successful tasks merge file deltas only
when the canonical workspace has not changed the same path. OS-level locking
serializes managers across threads and processes. Abandoned leases are reclaimed
only after their recorded owner process is confirmed dead.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator
from uuid import uuid4

from runtime.process_lock import exclusive_process_lock


SKIP_DIRECTORIES = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "node_modules", ".ai-team-workspaces", ".ai-team-dev-workspaces",
})
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_METADATA_SCHEMA = 1


class WorkspaceMergeConflict(RuntimeError):
    """A task lease and the canonical workspace changed the same path."""


@dataclass(frozen=True)
class WorkspaceLease:
    task_id: str
    root: Path
    base_hashes: dict[str, str]
    lease_id: str = ""


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
        managed_directories = [name for name in directories if name not in SKIP_DIRECTORIES]
        if any((base / name).is_symlink() for name in managed_directories):
            return True
        if any((base / name).is_symlink() for name in filenames):
            return True
        directories[:] = managed_directories
    return False


def _process_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Unknown platform/process errors are treated conservatively.
        return True
    return True


class DeveloperWorkspaceManager:
    """Issue isolated task workspaces and merge only conflict-free deltas."""

    def __init__(self, main_root: str | Path) -> None:
        self.main_root = Path(main_root).resolve()
        self.main_root.mkdir(parents=True, exist_ok=True)
        self._lease_parent = self.main_root.parent / ".ai-team-dev-workspaces"
        self._lock = threading.RLock()
        root_key = hashlib.sha256(str(self.main_root).encode("utf-8")).hexdigest()[:20]
        self._process_lock_path = self._lease_parent / f".manager-{root_key}.lock"
        with self._guard():
            self._recover_transactions_locked()
            self._recover_stale_leases_locked()

    @contextmanager
    def _guard(self) -> Iterator[None]:
        self._lease_parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with exclusive_process_lock(self._process_lock_path):
                yield

    @staticmethod
    def _metadata_path(lease_root: Path) -> Path:
        return lease_root.with_name(f"{lease_root.name}.lease.json")

    @staticmethod
    def _write_metadata(path: Path, payload: dict[str, object]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_metadata(self, lease_root: Path) -> dict[str, object]:
        path = self._metadata_path(lease_root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("workspace lease metadata is missing or invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _METADATA_SCHEMA
            or payload.get("lease_root") != lease_root.name
        ):
            raise ValueError("workspace lease metadata does not match this lease")
        return payload

    def _validate_lease(self, lease: WorkspaceLease) -> dict[str, object]:
        if not isinstance(lease, WorkspaceLease):
            raise TypeError("lease must be a WorkspaceLease")
        root = lease.root
        if root.parent.resolve() != self._lease_parent.resolve() or root.is_symlink() or not root.is_dir():
            raise ValueError("lease root is not owned by this workspace manager")
        metadata = self._read_metadata(root)
        if metadata.get("lease_id") != lease.lease_id or metadata.get("task_id") != lease.task_id:
            raise ValueError("workspace lease identity does not match its durable metadata")
        if metadata.get("owner_pid") != os.getpid():
            raise ValueError("workspace lease can only be merged by its owning process")
        return metadata

    def _recover_stale_leases_locked(self) -> list[str]:
        """Remove only incomplete or provably abandoned lease directories."""
        recovered: list[str] = []
        if not self._lease_parent.exists():
            return recovered
        for root in sorted(self._lease_parent.iterdir()):
            if not root.is_dir() or root.is_symlink() or root.name.startswith("."):
                continue
            metadata_path = self._metadata_path(root)
            if not metadata_path.exists():
                # A lease without metadata was never returned to a caller:
                # issue() writes metadata atomically before returning.
                shutil.rmtree(root, ignore_errors=True)
                recovered.append(root.name)
                continue
            try:
                metadata = self._read_metadata(root)
            except ValueError:
                # Corrupt metadata is not proof that the owner is dead.
                # Preserve it for operator inspection rather than risk data loss.
                continue
            if _process_is_alive(metadata.get("owner_pid")):
                continue
            shutil.rmtree(root, ignore_errors=True)
            metadata_path.unlink(missing_ok=True)
            recovered.append(root.name)
        return recovered

    def recover_stale_leases(self) -> tuple[str, ...]:
        """Reclaim leases whose owner process has exited; preserve live/unknown owners."""
        with self._guard():
            return tuple(self._recover_stale_leases_locked())

    def issue(self, task_id: str) -> WorkspaceLease:
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or task_id in {".", ".."}:
            raise ValueError("task_id must be a safe non-empty identifier")
        with self._guard():
            self._recover_transactions_locked()
            self._recover_stale_leases_locked()
            if _contains_symlink(self.main_root):
                raise ValueError("symbolic links in the canonical workspace are not allowed")
            lease_id = uuid4().hex
            lease_root = self._lease_parent / f"{task_id}-{lease_id}"
            lease_root.mkdir(parents=False, exist_ok=False)
            metadata_path = self._metadata_path(lease_root)
            try:
                self._copy_tree(self.main_root, lease_root)
                base_hashes = _tree_hashes(lease_root)
                self._write_metadata(metadata_path, {
                    "schema_version": _METADATA_SCHEMA,
                    "lease_id": lease_id,
                    "lease_root": lease_root.name,
                    "task_id": task_id,
                    "owner_pid": os.getpid(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except BaseException:
                shutil.rmtree(lease_root, ignore_errors=True)
                metadata_path.unlink(missing_ok=True)
                raise
            return WorkspaceLease(task_id, lease_root, base_hashes, lease_id)

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())

    def _transaction_journal_path(self, transaction_root: Path) -> Path:
        return transaction_root / "journal.json"

    def _write_transaction_journal(
        self, transaction_root: Path, payload: dict[str, object]
    ) -> None:
        self._write_metadata(self._transaction_journal_path(transaction_root), payload)

    def _rollback_transaction(self, transaction_root: Path, journal: dict[str, object]) -> None:
        operations = journal.get("operations")
        if not isinstance(operations, list):
            raise ValueError("workspace transaction journal has invalid operations")
        for operation in reversed(operations):
            if not isinstance(operation, dict) or not isinstance(operation.get("path"), str):
                raise ValueError("workspace transaction journal contains an invalid operation")
            relative = _relative_path(operation["path"])
            destination = self.main_root / relative
            self._assert_safe_destination(destination)
            existed = operation.get("existed") is True
            if existed:
                backup_name = operation.get("backup")
                if not isinstance(backup_name, str):
                    raise ValueError("workspace transaction journal is missing a backup")
                backup = transaction_root / _relative_path(backup_name)
                if not backup.is_file():
                    raise ValueError(f"workspace transaction backup is missing: {backup_name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._assert_safe_destination(destination)
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=f".{destination.name}.",
                    suffix=".rollback-tmp", delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                try:
                    shutil.copy2(backup, temporary_path)
                    os.replace(temporary_path, destination)
                finally:
                    temporary_path.unlink(missing_ok=True)
            else:
                if destination.is_file() and not destination.is_symlink():
                    destination.unlink()

    def _recover_transactions_locked(self) -> list[str]:
        recovered: list[str] = []
        if not self._lease_parent.exists():
            return recovered
        for transaction_root in sorted(self._lease_parent.glob(".txn-*")):
            if not transaction_root.is_dir() or transaction_root.is_symlink():
                continue
            journal_path = self._transaction_journal_path(transaction_root)
            if not journal_path.exists():
                # A transaction without a journal was never allowed to mutate
                # the canonical workspace.
                shutil.rmtree(transaction_root, ignore_errors=True)
                recovered.append(transaction_root.name)
                continue
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(journal, dict)
                    or journal.get("schema_version") != _METADATA_SCHEMA
                    or journal.get("transaction_root") != transaction_root.name
                ):
                    raise ValueError("workspace transaction journal identity mismatch")
                if journal.get("status") != "committed":
                    self._rollback_transaction(transaction_root, journal)
                shutil.rmtree(transaction_root, ignore_errors=True)
                recovered.append(transaction_root.name)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                # Never discard an incomplete or corrupt recovery record.
                continue
        return recovered

    def merge(self, lease: WorkspaceLease) -> MergeReport:
        with self._guard():
            self._recover_transactions_locked()
            self._validate_lease(lease)
            if _contains_symlink(lease.root):
                raise ValueError("symbolic links are not allowed in a developer workspace")
            if _contains_symlink(self.main_root):
                raise ValueError("symbolic links in the canonical workspace are not allowed")

            local = _tree_hashes(lease.root)
            canonical = _tree_hashes(self.main_root)
            base = lease.base_hashes

            conflicts: list[str] = []
            for name in sorted(set(base) | set(local)):
                _relative_path(name)
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

            changed = [name for name in sorted(local) if name in base and local[name] != base[name]]
            added = [name for name in sorted(local) if name not in base]
            deleted = [name for name in sorted(set(base) - set(local))]
            operations: list[dict[str, object]] = []
            for name in changed + added + deleted:
                relative = _relative_path(name)
                destination = self.main_root / relative
                self._assert_safe_destination(destination)
                existed = destination.is_file() and not destination.is_symlink()
                if name in changed or name in deleted:
                    if not existed:
                        raise WorkspaceMergeConflict(
                            f"canonical file disappeared before merge: {name}"
                        )
                elif existed or destination.exists():
                    raise WorkspaceMergeConflict(
                        f"canonical path appeared before add: {name}"
                    )
                operations.append({
                    "path": name,
                    "kind": "delete" if name in deleted else "write",
                    "existed": existed,
                    "backup": f"backup/{name}" if existed else None,
                    "staged": f"staged/{name}" if name not in deleted else None,
                })

            transaction_root = self._lease_parent / f".txn-{uuid4().hex}"
            (transaction_root / "backup").mkdir(parents=True)
            (transaction_root / "staged").mkdir()
            try:
                for operation in operations:
                    name = str(operation["path"])
                    relative = _relative_path(name)
                    destination = self.main_root / relative
                    if operation["existed"]:
                        backup = transaction_root / str(operation["backup"])
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(destination, backup)
                        self._fsync_file(backup)
                    if operation["kind"] == "write":
                        staged = transaction_root / str(operation["staged"])
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        source = lease.root / relative
                        shutil.copy2(source, staged)
                        self._fsync_file(staged)

                journal: dict[str, object] = {
                    "schema_version": _METADATA_SCHEMA,
                    "transaction_root": transaction_root.name,
                    "task_id": lease.task_id,
                    "lease_id": lease.lease_id,
                    "status": "prepared",
                    "operations": operations,
                }
                self._write_transaction_journal(transaction_root, journal)
                journal["status"] = "applying"
                self._write_transaction_journal(transaction_root, journal)

                for operation in operations:
                    relative = _relative_path(str(operation["path"]))
                    destination = self.main_root / relative
                    self._assert_safe_destination(destination)
                    if operation["kind"] == "delete":
                        destination.unlink()
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    self._assert_safe_destination(destination)
                    staged = transaction_root / str(operation["staged"])
                    with tempfile.NamedTemporaryFile(
                        dir=destination.parent, prefix=f".{destination.name}.",
                        suffix=".merge-tmp", delete=False,
                    ) as temporary:
                        temporary_path = Path(temporary.name)
                    try:
                        shutil.copy2(staged, temporary_path)
                        os.replace(temporary_path, destination)
                    finally:
                        temporary_path.unlink(missing_ok=True)

                journal["status"] = "committed"
                self._write_transaction_journal(transaction_root, journal)
                shutil.rmtree(transaction_root, ignore_errors=True)
            except BaseException:
                journal_path = self._transaction_journal_path(transaction_root)
                if journal_path.exists():
                    try:
                        current_journal = json.loads(journal_path.read_text(encoding="utf-8"))
                        self._rollback_transaction(transaction_root, current_journal)
                        shutil.rmtree(transaction_root, ignore_errors=True)
                    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                        # Keep the journal and backups for recovery on next startup.
                        pass
                else:
                    shutil.rmtree(transaction_root, ignore_errors=True)
                raise

            return MergeReport(lease.task_id, tuple(changed), tuple(added), tuple(deleted))

    def _assert_safe_destination(self, destination: Path) -> None:
        relative = destination.relative_to(self.main_root)
        current = self.main_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"symbolic link in canonical destination path: {current}")
        resolved = destination.resolve(strict=False)
        if not resolved.is_relative_to(self.main_root):
            raise ValueError(f"workspace destination escapes canonical root: {destination}")

    def discard(self, lease: WorkspaceLease) -> None:
        with self._guard():
            self._validate_lease(lease)
            shutil.rmtree(lease.root, ignore_errors=True)
            self._metadata_path(lease.root).unlink(missing_ok=True)

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
