"""Deterministic requirement-acceptance verification.

Reviewer judges code quality; this module judges **product requirement
conformance** (optional_plan #17): every requirement the analyst numbered
(REQ-xxx) must be traceable through the delivery — the requirements document,
the design document, and the test report — and every "必须"-level requirement
must carry acceptance criteria.

The check is deliberately deterministic (string presence over authoritative
artifacts), never an LLM judgment, so the verdict is reproducible and auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REQ_TOKEN = re.compile(r"REQ-\d{3,}")
_PRIORITY_TOKENS = ("必须", "应该", "可选")

# Sources every non-optional requirement must be traceable through.
REQUIRED_COVERAGE_SOURCES = ("requirements_doc", "test_report")


@dataclass(frozen=True)
class RequirementEntry:
    """One parsed requirement from the analyst's draft specification."""

    req_id: str
    priority: str | None
    has_acceptance_criteria: bool
    title: str | None


def parse_requirement_entries(analysis: str) -> list[RequirementEntry]:
    """Parse REQ-xxx entries from the analyst's markdown draft.

    Real drafts express one requirement in several places (a list row, a
    dedicated acceptance-criteria subsection, an AC table), so all blocks
    sharing an id are MERGED: a requirement passes the acceptance-criteria
    check when ANY of its blocks contains one, and the priority is the first
    stated. Sections titled 验收 (acceptance) mark their contents as
    acceptance criteria even without per-line keywords.
    """
    if not isinstance(analysis, str):
        raise TypeError("analysis must be a string")

    collected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    current_id: str | None = None
    current_section = ""

    for line in analysis.splitlines():
        stripped = line.strip()
        is_section_header = (
            stripped.startswith("## ")
            and not stripped.startswith("### ")
        )
        match = _REQ_TOKEN.search(line)
        if match is not None:
            req_id = match.group(0)
            if req_id not in collected:
                collected[req_id] = {"title": "", "priority": None, "blocks": [], "sections": []}
                order.append(req_id)
            info = collected[req_id]
            title = line.replace(match.group(0), "").strip().lstrip("#").strip()
            for token in _PRIORITY_TOKENS:
                title = title.replace(f"（{token}）", "").replace(f"({token})", "").strip()
            if not info["title"]:
                info["title"] = title.strip("-* ").strip()
            if info["priority"] is None:
                info["priority"] = next(
                    (token for token in _PRIORITY_TOKENS if token in line), None
                )
            info["blocks"].append([line])
            info["sections"].append(current_section)
            current_id = req_id
        elif current_id is not None:
            if is_section_header or stripped.startswith("#"):
                if is_section_header:
                    current_section = stripped.lstrip("#").strip()
                current_id = None
            else:
                collected[current_id]["blocks"][-1].append(line)
        elif is_section_header:
            current_section = stripped.lstrip("#").strip()

    entries: list[RequirementEntry] = []
    for req_id in order:
        info = collected[req_id]
        block_text = "\n".join("\n".join(block) for block in info["blocks"])
        section_text = "\n".join(info["sections"])
        priority = info["priority"] or next(
            (token for token in _PRIORITY_TOKENS if token in block_text), None
        )
        criteria_in_section = "验收" in section_text
        criteria_by_marker = any(
            "AC-" in block_line for block in info["blocks"] for block_line in block
        )
        entries.append(RequirementEntry(
            req_id=req_id,
            priority=priority,
            has_acceptance_criteria=(
                "验收" in block_text or criteria_in_section or criteria_by_marker
            ),
            title=info["title"] or None,
        ))
    return entries


def build_traceability_matrix(
    entries: list[RequirementEntry],
    *,
    sources: dict[str, str],
) -> list[dict[str, Any]]:
    """One row per requirement: where its id is referenced.

    ``sources`` maps a coverage-source name (e.g. ``requirements_doc``,
    ``design_doc``, ``test_report``, ``user_manual``, ``implementation_reports``)
    to the text to search. Missing sources count as uncovered.
    """
    rows: list[dict[str, Any]] = []
    for entry in entries:
        row: dict[str, Any] = {
            "req_id": entry.req_id,
            "priority": entry.priority,
            "title": entry.title,
            "has_acceptance_criteria": entry.has_acceptance_criteria,
        }
        for name, content in sources.items():
            row[f"in_{name}"] = bool(content) and entry.req_id in content
        rows.append(row)
    return rows


def acceptance_verdict(
    entries: list[RequirementEntry],
    matrix: list[dict[str, Any]],
) -> dict[str, Any]:
    """Judge delivery conformance from the traceability matrix.

    必须-level requirements must appear in every required coverage source and
    carry acceptance criteria; missing ones are gaps (verdict ``failed``).
    应该/可选 requirements only produce warnings — they never fail delivery.
    """
    rows = {row["req_id"]: row for row in matrix}
    gaps: list[str] = []
    warnings: list[str] = []
    for entry in entries:
        row = rows.get(entry.req_id)
        if row is None:
            continue
        missing = [
            name
            for name in REQUIRED_COVERAGE_SOURCES
            if not row.get(f"in_{name}")
        ]
        if entry.priority == "可选":
            if missing:
                warnings.append(f"{entry.req_id}（可选）未在 {', '.join(missing)} 中追溯")
            continue
        if entry.priority == "必须" and not entry.has_acceptance_criteria:
            gaps.append(f"{entry.req_id} 缺少验收标准")
        if missing:
            message = f"{entry.req_id} 未在 {', '.join(missing)} 中追溯"
            if entry.priority == "必须":
                gaps.append(message)
            else:
                warnings.append(message)
    return {
        "verdict": "failed" if gaps else "passed",
        "gaps": gaps,
        "warnings": warnings,
        "total_requirements": len(entries),
    }


def render_acceptance_report(
    entries: list[RequirementEntry],
    matrix: list[dict[str, Any]],
    verdict: dict[str, Any],
    *,
    project: str | None = None,
) -> str:
    """Render the deterministic acceptance report as markdown."""
    source_names = sorted({
        key[len("in_"):]
        for row in matrix
        for key in row
        if key.startswith("in_")
    })
    lines = ["# 需求验收报告（Acceptance Report）", ""]
    if project:
        lines += [f"项目：{project}", ""]
    lines += [
        f"验收结论：**{verdict['verdict'].upper()}**",
        "",
        f"需求总数：{verdict['total_requirements']}",
        "",
        "| 需求 | 优先级 | 验收标准 | " + " | ".join(source_names) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in source_names) + " |",
    ]
    rows = {row["req_id"]: row for row in matrix}
    for entry in entries:
        row = rows.get(entry.req_id, {})
        cells = [
            "是" if row.get(f"in_{name}") else "否"
            for name in source_names
        ]
        lines.append(
            f"| {entry.req_id} | {entry.priority or '未标注'} "
            f"| {'是' if entry.has_acceptance_criteria else '否'} | "
            + " | ".join(cells) + " |"
        )
    if verdict["gaps"]:
        lines += ["", "## 验收缺口", ""]
        lines += [f"- {gap}" for gap in verdict["gaps"]]
    if verdict["warnings"]:
        lines += ["", "## 警告", ""]
        lines += [f"- {warning}" for warning in verdict["warnings"]]
    lines += [
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
    ]
    return "\n".join(lines) + "\n"


def write_acceptance_report(
    docs_root: Path,
    entries: list[RequirementEntry],
    matrix: list[dict[str, Any]],
    verdict: dict[str, Any],
    *,
    project: str | None = None,
    filename: str = "acceptance_report.md",
) -> Path:
    """Write the acceptance report into the delivery docs directory."""
    docs_root = Path(docs_root)
    docs_root.mkdir(parents=True, exist_ok=True)
    target = docs_root / filename
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        render_acceptance_report(entries, matrix, verdict, project=project),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
