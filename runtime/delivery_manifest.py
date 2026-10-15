"""Deterministic delivery manifest generation.

After the product and its documentation set are complete, the delivery phase
writes a manifest the customer can check against on receipt: every deliverable
file with size and SHA-256 checksum. Runtime artifacts (`__pycache__`,
`.pytest_cache`, virtualenvs) are excluded — only what a customer receives is
listed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRECTORIES = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".venv",
    ".git",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
})

EXCLUDED_FILES = frozenset({
    ".gitignore",
    ".pytest_cache",
})


def _is_deliverable(path: Path) -> bool:
    if any(part in EXCLUDED_DIRECTORIES for part in path.parts):
        return False
    return path.name not in EXCLUDED_FILES


def collect_deliverables(root: str | Path) -> list[dict[str, object]]:
    """Return one entry per deliverable file under ``root`` (sorted by path)."""
    base = Path(root)
    if not base.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or not _is_deliverable(path.relative_to(base)):
            continue
        data = path.read_bytes()
        entries.append({
            "path": path.relative_to(base).as_posix(),
            "size": len(data),
            "checksum": hashlib.sha256(data).hexdigest(),
        })
    return entries


def render_delivery_manifest(
    entries: list[dict[str, object]],
    *,
    project: str | None = None,
) -> str:
    """Render the human-readable manifest markdown for the given entries."""
    lines = ["# 交付清单（Delivery Manifest）", ""]
    if project:
        lines += [f"项目：{project}", ""]
    lines += ["| 文件 | 大小（字节） | SHA-256 |", "| --- | --- | --- |"]
    for entry in entries:
        lines.append(f"| {entry['path']} | {entry['size']} | {entry['checksum']} |")
    lines += [
        "",
        f"共 {len(entries)} 个文件。校验方式：`sha256sum <文件>` 应与上表一致。",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
    ]
    return "\n".join(lines) + "\n"


def write_delivery_manifest(
    root: str | Path,
    *,
    project: str | None = None,
    filename: str = "DELIVERY_MANIFEST.md",
) -> Path:
    """Collect deliverables under ``root`` and write the manifest there."""
    base = Path(root)
    entries = collect_deliverables(base)
    manifest = render_delivery_manifest(entries, project=project)
    target = base / filename
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(manifest, encoding="utf-8")
    os_replace(temporary, target)
    return target


def os_replace(source: Path, target: Path) -> None:
    source.replace(target)
