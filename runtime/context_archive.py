"""Shared context archive: one folder that preserves every task's history.

Developer workspaces are isolated from each other, so the archive is the
shared memory: each terminal task writes its full record (result, tool
history, feedback, merge report) into ``.context-archive/tasks/`` and the
index is refreshed. Later tasks receive the index listing in their context
and can read any record file directly with read_file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ContextArchive:
    DIRNAME = ".context-archive"
    TASKS_SUBDIR = "tasks"
    INDEX_NAME = "index.json"
    MAX_INDEX_ENTRIES = 40

    def __init__(self, root: str | Path, namespace: str = "default") -> None:
        safe = self._sanitize_namespace(namespace)
        self.root = Path(root) / self.DIRNAME / safe
        self.tasks_dir = self.root / self.TASKS_SUBDIR

    @staticmethod
    def _sanitize_namespace(namespace: str) -> str:
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("archive namespace must be a non-empty string")
        safe = namespace.strip()
        if "/" in safe or "\\" in safe or safe in {".", ".."} or Path(safe).name != safe:
            raise ValueError(f"archive namespace must be path-safe: {namespace!r}")
        return safe

    def record_task(self, record: dict[str, Any]) -> Path:
        task_id = record.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("archive record requires a non-empty task_id")
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        path = self.tasks_dir / f"{task_id}.json"
        self._atomic_write(path, record)
        self._refresh_index()
        return path

    def index_summary(self) -> list[dict[str, Any]]:
        index_path = self.root / self.INDEX_NAME
        if not index_path.is_file():
            return []
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = payload.get("tasks") if isinstance(payload, dict) else None
        return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []

    def context_injection(self) -> str:
        """Render the archive index for a developer prompt (empty if none)."""
        return self.render_index(self.index_summary(), base_path=self.workspace_relative_base())

    def workspace_relative_base(self) -> str:
        """Archive location as seen from the workspace root the model uses."""
        return f"{self.DIRNAME}/"

    @staticmethod
    def render_index(entries: list[dict[str, Any]], *, base_path: str = ".context-archive/") -> str:
        if not entries:
            return ""
        lines = [
            "",
            "====================",
            f"任务历史档案（从你的工作区根目录用 read_file 读取，路径前缀：{base_path}）",
            "====================",
        ]
        for entry in entries[: ContextArchive.MAX_INDEX_ENTRIES]:
            lines.append(
                f"- {base_path}tasks/{entry.get('task_id')}.json | {entry.get('role')} "
                f"| {entry.get('status')} | {entry.get('title')} "
                f"| 变更文件 {entry.get('changed_files', 0)} 个 | {entry.get('summary', '')}"
            )
        return "\n".join(lines) + "\n"

    def _refresh_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            merge = record.get("merge_report") if isinstance(record.get("merge_report"), dict) else {}
            changed = merge.get("changed", [])
            added = merge.get("added", [])
            entries.append({
                "task_id": record.get("task_id"),
                "role": record.get("role"),
                "title": record.get("title"),
                "status": record.get("status"),
                "changed_files": len(changed) + len(added),
                "summary": str(record.get("message", ""))[:200],
            })
        self._atomic_write(self.root / self.INDEX_NAME, {"tasks": entries})

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


def build_task_archive_record(
    task_dict: dict[str, Any],
    *,
    developer_slot: int,
    merge_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Freeze one task's durable history for the shared archive."""
    context = task_dict.get("context") if isinstance(task_dict.get("context"), dict) else {}
    return {
        "task_id": task_dict.get("task_id") or task_dict.get("id"),
        "role": task_dict.get("role"),
        "title": task_dict.get("title"),
        "status": task_dict.get("status"),
        "message": str(task_dict.get("result", {}).get("message", "") if isinstance(task_dict.get("result"), dict) else task_dict.get("result", ""))[:4000],
        "error": task_dict.get("error"),
        "developer_slot": developer_slot,
        "merge_report": merge_report,
        # Append-only histories preserve every round's evidence; the
        # single-slot feedback fields only hold the latest round's input.
        "status_history": task_dict.get("status_history"),
        "review_history": task_dict.get("review_history"),
        "test_history": task_dict.get("test_history"),
        "review_result": task_dict.get("review_result"),
        "test_result": task_dict.get("test_result"),
        "tester_feedback": context.get("tester_feedback"),
        "qa_feedback": context.get("qa_feedback"),
        "reviewer_feedback": context.get("reviewer_feedback"),
        "tool_execution_history": context.get("tool_execution_history"),
        "result": task_dict.get("result"),
    }
