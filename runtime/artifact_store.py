"""Content-addressed artifact storage for large runtime outputs.

Large tool outputs previously lived in full inside ``ToolExecutionHistory``
records, which travel through ``task.context`` and every project snapshot:
checkpoint serialization cost grew without bound. This store keeps the
authoritative large payloads on disk instead, while callers keep only the
immutable ``ArtifactRecord`` (id, checksum, size, path) in runtime state -
the optional_plan "Artifact Store" item and the snapshot-growth fix.

Layout under the store root:

    objects/<checksum[:2]>/<checksum>   content-addressed payload (dedup)
    records/<artifact_id>.json          immutable record document

Writes are atomic (temporary file + ``os.replace``). Records are checksum-
verified on every read, so silent corruption is detectable.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError("metadata must be JSON serializable") from exc


@dataclass(frozen=True)
class ArtifactRecord:
    """Immutable reference to one archived large payload."""

    artifact_id: str
    kind: str
    checksum: str
    size: int
    path: str
    mime_type: str
    created_at: str
    task_id: str | None = None
    project_id: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "checksum": self.checksum,
            "size": self.size,
            "path": self.path,
            "mime_type": self.mime_type,
            "created_at": self.created_at,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRecord":
        if not isinstance(payload, dict):
            raise TypeError("artifact record payload must be a dictionary")
        required = {
            "artifact_id",
            "kind",
            "checksum",
            "size",
            "path",
            "mime_type",
            "created_at",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"artifact record missing fields: {sorted(missing)}")
        return cls(
            artifact_id=payload["artifact_id"],
            kind=payload["kind"],
            checksum=payload["checksum"],
            size=payload["size"],
            path=payload["path"],
            mime_type=payload["mime_type"],
            created_at=payload["created_at"],
            task_id=payload.get("task_id"),
            project_id=payload.get("project_id"),
            metadata=payload.get("metadata") or {},
        )


class FilesystemArtifactStore:
    """Filesystem-backed content-addressed artifact storage."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "records").mkdir(exist_ok=True)

    def _record_path(self, artifact_id: str) -> Path:
        return self.root / "records" / f"{artifact_id}.json"

    def _object_path(self, checksum: str) -> Path:
        return self.root / "objects" / checksum[:2] / checksum

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def store(
        self,
        content: str | bytes,
        *,
        kind: str,
        task_id: str | None = None,
        project_id: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        """Archive one payload and return its immutable record.

        Content-addressed: archiving identical content twice stores one
        object; each archive still receives its own record with a distinct
        ``artifact_id`` so every reference stays individually traceable.
        """
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("kind must be a non-empty string")
        if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
            raise ValueError("task_id must be a non-empty string or None")
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary or None")

        if isinstance(content, str):
            data = content.encode("utf-8")
            resolved_mime = mime_type or "text/plain"
        elif isinstance(content, bytes):
            data = content
            resolved_mime = mime_type or "application/octet-stream"
        else:
            raise TypeError("content must be str or bytes")

        checksum = hashlib.sha256(data).hexdigest()
        object_path = self._object_path(checksum)
        if not object_path.exists():
            self._atomic_write(object_path, data)

        record = ArtifactRecord(
            artifact_id=uuid.uuid4().hex,
            kind=kind,
            checksum=checksum,
            size=len(data),
            path=str(object_path),
            mime_type=resolved_mime,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            task_id=task_id,
            project_id=project_id,
            metadata=_json_safe(metadata or {}),
        )
        self._atomic_write(
            self._record_path(record.artifact_id),
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return record

    def get(self, artifact_id: str) -> ArtifactRecord:
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ValueError("artifact_id must be a non-empty string")
        path = self._record_path(artifact_id)
        if not path.is_file():
            raise KeyError(artifact_id)
        try:
            record = ArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid artifact record: {artifact_id}") from exc
        if record.artifact_id != artifact_id:
            raise ValueError("artifact record identity does not match filename")
        return record

    def read_bytes(self, artifact_id: str) -> bytes:
        """Return the archived payload, verifying its checksum on read."""
        record = self.get(artifact_id)
        payload = Path(record.path).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record.checksum:
            raise ValueError(f"artifact checksum mismatch: {artifact_id}")
        return payload

    def read_text(self, artifact_id: str, *, errors: str = "replace") -> str:
        payload = self.read_bytes(artifact_id)
        return payload.decode("utf-8", errors=errors)

    def delete(self, artifact_id: str) -> None:
        record = self.get(artifact_id)
        self._record_path(artifact_id).unlink()
        object_path = Path(record.path)
        # Content-addressed objects may be shared by several records; unlink
        # only when this was the last reference in the store.
        for candidate in (self.root / "records").glob("*.json"):
            try:
                other = ArtifactRecord.from_dict(
                    json.loads(candidate.read_text(encoding="utf-8"))
                )
            except (json.JSONDecodeError, ValueError, OSError):
                continue
            if other.checksum == record.checksum:
                return
        try:
            object_path.unlink()
        except FileNotFoundError:
            pass

    def count(self) -> int:
        """Return the number of stored artifact records (diagnostics helper)."""
        return sum(1 for _ in (self.root / "records").glob("*.json"))
