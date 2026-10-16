"""Deterministic recovery seed for guard-retried developer rounds.

When the progress guard trips mid-round, the retry's greatest risk is that
the model re-reads the same files it already read, burning the round without
progress. The seed removes that incentive mechanically: the current contents
of the files the previous round touched are inlined into the retry prompt,
so re-reading is unnecessary and the rework protocol forbids it.
"""
from __future__ import annotations

from typing import Any

SEED_PER_FILE_CAP = 4000
SEED_TOTAL_CAP = 20_000
SEED_MAX_FILES = 8


def collect_history_paths(history_payload: list[dict[str, Any]] | None) -> list[str]:
    """Deduped, order-stable file paths read or written in the previous round."""
    if not isinstance(history_payload, list):
        return []
    paths: list[str] = []
    for record in history_payload:
        if not isinstance(record, dict):
            continue
        if record.get("tool_name") not in {"read_file", "write_file"}:
            continue
        arguments = record.get("arguments")
        path = arguments.get("path") if isinstance(arguments, dict) else None
        if isinstance(path, str) and path.strip() and path not in paths:
            paths.append(path)
    return paths[:SEED_MAX_FILES]


def build_recovery_seed(
    reason: str,
    entries: list[tuple[str, str | None]],
    *,
    per_file_cap: int = SEED_PER_FILE_CAP,
    total_cap: int = SEED_TOTAL_CAP,
) -> str:
    """Render the recovery checkpoint section for a retry prompt.

    Each entry is (path, content or None). None means the file could not be
    read back (missing or unreadable) — the path is still listed so the
    model knows what existed, without inventing contents.
    """
    lines = [
        "",
        "====================",
        "恢复检查点（上一轮被进度守卫拦截后的续跑起点）",
        "====================",
        f"拦截原因：{reason}",
        "以下是上一轮你已读取或修改过的文件的当前内容；它们已在上下文中，禁止再用 read_file 读取这些文件。",
        "直接按返工守则行动：定位问题、修改文件、用 python -m pytest 复跑收集新证据。",
        "",
    ]
    used = 0
    for path, content in entries:
        if used >= total_cap:
            lines.append(f"[已达恢复检查点内容上限，其余文件省略：{path}]")
            continue
        if content is None:
            lines.append(f"----- {path}（内容不可读，如需要请用 read_file 重新获取一次）-----")
            continue
        text = content if len(content) <= per_file_cap else content[:per_file_cap] + f"\n…[截断，共 {len(content)} 字符]"
        remaining = total_cap - used
        if len(text) > remaining:
            text = text[:remaining] + "\n…[已达恢复检查点内容上限]"
        used += len(text)
        lines.append(f"----- {path} -----")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
