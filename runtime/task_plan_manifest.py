"""The frozen task plan manifest: who runs what, recorded and immutable.

Once the planner's task graph is accepted, the manifest freezes every node
(id, role, title, dependencies) plus its dispatch facts (developer slot,
status). Execution must follow the plan step by step: before work starts the
live graph is verified against the frozen structural hash, and any drift is
a hard error. A legitimately re-planned graph (recovery REPLAN, customer
change request) must explicitly freeze a new version instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.context_archive import ContextArchive


class TaskPlanDriftError(RuntimeError):
    """The live task graph no longer matches the frozen task plan."""


def _structural_hash(tasks: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "id": task["id"],
            "role": task["role"],
            "title": task["title"],
            "dependencies": sorted(task.get("dependencies") or []),
        }
        for task in tasks
    ]
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class TaskPlanManifest:
    DIRNAME = ".context-archive"
    FILENAME = "task_plan.json"

    def __init__(self, root: str | Path, namespace: str = "default") -> None:
        safe = ContextArchive._sanitize_namespace(namespace)
        self.path = Path(root) / self.DIRNAME / safe / self.FILENAME

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid task plan manifest: {self.path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            raise ValueError(f"invalid task plan manifest: {self.path}")
        return payload

    def task_dicts(self, tasks: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": task.id,
                "role": task.role,
                "title": task.title,
                "dependencies": list(task.dependencies),
            }
            for task in tasks
        ]

    def freeze(self, tasks: list[Any], *, reason: str) -> dict[str, Any]:
        """Freeze the current graph as a new plan version and return it."""
        entries = self.task_dicts(tasks)
        previous = self.load()
        version = 1
        if previous is not None and previous.get("plan_hash") != _structural_hash(entries):
            version = int(previous.get("version", 1)) + 1
        payload: dict[str, Any] = {
            "version": version,
            "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": reason,
            "plan_hash": _structural_hash(entries),
            "entries": [
                {
                    "task_id": entry["id"],
                    "role": entry["role"],
                    "title": entry["title"],
                    "dependencies": entry["dependencies"],
                    "developer_slot": None,
                    "status": "planned",
                }
                for entry in entries
            ],
        }
        if previous is not None and previous.get("plan_hash") == payload["plan_hash"]:
            # Same graph re-frozen (e.g. a resume): keep dispatch facts.
            payload["version"] = int(previous.get("version", 1))
            payload["entries"] = previous["entries"]
        self._write(payload)
        self._write_markdown(payload)
        return payload

    def verify(self, tasks: list[Any]) -> dict[str, Any]:
        """Raise TaskPlanDriftError unless the live graph matches the freeze."""
        payload = self.load()
        if payload is None:
            raise TaskPlanDriftError("no task plan manifest is frozen for this workspace")
        live = self.task_dicts(tasks)
        if _structural_hash(live) != payload.get("plan_hash"):
            raise TaskPlanDriftError(
                f"live task graph drifted from frozen task plan v{payload.get('version')}; "
                "execution must follow the frozen plan or explicitly re-freeze it"
            )
        return payload

    def record_dispatch(self, task_id: str, developer_slot: int) -> None:
        self._mutate_entry(task_id, lambda entry: {
            **entry,
            "developer_slot": int(developer_slot),
            "status": "dispatched",
        })

    def record_completion(self, task_id: str, status: str) -> None:
        self._mutate_entry(task_id, lambda entry: {**entry, "status": str(status)})

    def _mutate_entry(self, task_id: str, mutate) -> None:
        payload = self.load()
        if payload is None:
            return
        entries = payload.get("entries", [])
        for index, entry in enumerate(entries):
            if entry.get("task_id") == task_id:
                entries[index] = mutate(entry)
                break
        self._write(payload)
        self._write_markdown(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".task-plan-", suffix=".tmp", dir=self.path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _write_markdown(self, payload: dict[str, Any]) -> None:
        lines = [
            f"# 任务计划清单（task plan v{payload['version']}，已冻结）",
            "",
            f"冻结时间：{payload['frozen_at']}  |  冻结原因：{payload['reason']}  |  plan_hash：`{payload['plan_hash'][:16]}…`",
            "",
            "| 任务 | 角色 | 派发 Developer | 依赖 | 状态 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for entry in payload["entries"]:
            slot = entry.get("developer_slot")
            lines.append(
                f"| {entry['task_id']} {entry['title']} | {entry['role']} "
                f"| {'dev-' + str(slot) if slot is not None else '未派发'} "
                f"| {', '.join(entry['dependencies']) or '—'} | {entry['status']} |"
            )
        markdown_path = self.path.with_name("task_plan.md")
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
