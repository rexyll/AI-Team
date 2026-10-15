from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Callable, TypeVar

from runtime.multi_process import TaskLease
from runtime.process_lock import exclusive_process_lock


T = TypeVar("T")


class DurableTaskLeaseStore:
    """Filesystem-backed lease store with process-safe task-level fencing."""

    def __init__(self, root: str | Path, *, clock=None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._clock = clock or __import__("time").monotonic
        self._lock = RLock()

    def _path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not task_id.strip() or Path(task_id).name != task_id:
            raise ValueError("task_id must be a simple file-safe identifier")
        return self.root / f"{task_id}.lease.json"

    def _process_lock_path(self, task_id: str) -> Path:
        return self.root / f".{task_id}.lease.lock"

    def acquire(self, task_id: str, worker_id: str, lease_id: str, ttl_s: float) -> TaskLease | None:
        if not worker_id or not lease_id or ttl_s <= 0:
            raise ValueError("worker_id, lease_id and positive ttl_s are required")
        with exclusive_process_lock(self._process_lock_path(task_id)), self._lock:
            now = self._clock()
            current = self._load(task_id)
            if current and current.expires_at > now:
                return None
            lease = TaskLease(task_id, worker_id, lease_id, now + ttl_s)
            self._write(lease)
            return lease

    def renew(self, task_id: str, worker_id: str, lease_id: str, ttl_s: float) -> TaskLease | None:
        if ttl_s <= 0:
            raise ValueError("positive ttl_s is required")
        with exclusive_process_lock(self._process_lock_path(task_id)), self._lock:
            now = self._clock()
            current = self._load(task_id)
            if not current or current.expires_at <= now:
                return None
            if current.worker_id != worker_id or current.lease_id != lease_id:
                return None
            lease = TaskLease(task_id, worker_id, lease_id, now + ttl_s)
            self._write(lease)
            return lease

    def release(self, task_id: str, worker_id: str, lease_id: str) -> bool:
        with exclusive_process_lock(self._process_lock_path(task_id)), self._lock:
            current = self._load(task_id)
            if not current or current.worker_id != worker_id or current.lease_id != lease_id:
                return False
            self._path(task_id).unlink(missing_ok=True)
            return True

    def owner(self, task_id: str) -> TaskLease | None:
        with exclusive_process_lock(self._process_lock_path(task_id)), self._lock:
            now = self._clock()
            current = self._load(task_id)
            if not current:
                return None
            if current.expires_at <= now:
                self._path(task_id).unlink(missing_ok=True)
                return None
            return current

    def commit_if_owner(
        self,
        task_id: str,
        worker_id: str,
        lease_id: str,
        apply_result: Callable[[], T],
    ) -> T:
        """Validate ownership and apply a result inside the task fence.

        The process lock serializes this critical section across independent
        processes using the same filesystem reference backend. The callback is
        deliberately executed while the fence is held so a lease takeover
        cannot occur between ownership validation and the protected apply.
        """
        with exclusive_process_lock(self._process_lock_path(task_id)), self._lock:
            now = self._clock()
            current = self._load(task_id)
            if current is None:
                raise PermissionError("Task has no active worker lease")
            if current.expires_at <= now:
                self._path(task_id).unlink(missing_ok=True)
                raise PermissionError("Task has no active worker lease")
            if current.worker_id != worker_id or current.lease_id != lease_id:
                raise PermissionError("Worker lease ownership mismatch")
            return apply_result()

    def _load(self, task_id: str) -> TaskLease | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskLease(**data)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ValueError(f"Corrupt task lease: {task_id}")

    def _write(self, lease: TaskLease) -> None:
        path = self._path(lease.task_id)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(asdict(lease), indent=2), encoding="utf-8")
        temporary.replace(path)
