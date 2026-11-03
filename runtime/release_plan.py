"""Milestone release planning and cross-deliverable release history.

The single-requirement delivery already resolves a semver version per
deliverable (``runtime/release.py``, ``release_log.json``). This module adds
the project-management layer on top:

- a deterministic Markdown requirements/plan file with **milestones** and
  multiple requirements, parsed here into an ordered plan;
- a shared plan document that records one outcome per requirement (delivery
  status, acceptance, version/tag, deliverable root);
- a read-only aggregation view across every ``release_log.json`` found under
  a base directory.

Parsing is fail-closed: an empty plan, a requirement without a milestone, an
empty requirement body or an invalid explicit version raises instead of
silently dropping work.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.release import RELEASE_LOG_FILENAME, load_release_log, validate_semver

PLAN_TITLE_DEFAULT = "发布计划"
_MILESTONE_PREFIX = re.compile(r"^里程碑\s*[：:]?\s*")
_REQUIREMENT_PREFIX = re.compile(r"^需求\s*(?:[Rr](?:[Ee][Qq])?[-_]?\d*|\d*)?\s*[：:]")
_VERSION_SUFFIX = re.compile(r"\s*\[(?:v|版本\s*[：:]?)\s*([0-9A-Za-z.\-+]+)\]\s*$")
_HISTORY_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "venv", ".tox"})
DEFAULT_HISTORY_DEPTH = 3


@dataclass(frozen=True)
class ReleasePlanEntry:
    """One requirement in a milestone release plan."""

    index: int
    milestone: str
    title: str
    requirement: str
    version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.index, int) or isinstance(self.index, bool) or self.index < 1:
            raise ValueError("index must be a positive integer")
        for name in ("milestone", "title", "requirement"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.version is not None:
            validate_semver(self.version)


@dataclass(frozen=True)
class ReleasePlan:
    """An ordered milestone plan parsed from the customer's requirements file."""

    title: str
    entries: tuple[ReleasePlanEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("a release plan must define at least one requirement")
        if any(not isinstance(entry, ReleasePlanEntry) for entry in self.entries):
            raise TypeError("entries must be ReleasePlanEntry instances")

    @property
    def milestones(self) -> tuple[str, ...]:
        """Milestone labels in first-appearance order."""
        ordered: list[str] = []
        for entry in self.entries:
            if entry.milestone not in ordered:
                ordered.append(entry.milestone)
        return tuple(ordered)

    def entries_for(self, milestone: str) -> tuple[ReleasePlanEntry, ...]:
        return tuple(entry for entry in self.entries if entry.milestone == milestone)


def _normalize_milestone(text: str) -> str:
    label = _MILESTONE_PREFIX.sub("", text).strip()
    if not label:
        raise ValueError("milestone heading must carry a label")
    return label


def _parse_requirement_heading(text: str) -> tuple[str, str | None]:
    title = text.strip()
    version: str | None = None
    match = _VERSION_SUFFIX.search(title)
    if match:
        version = validate_semver(match.group(1))
        title = title[: match.start()].strip()
    prefix = _REQUIREMENT_PREFIX.match(title)
    if prefix:
        title = title[prefix.end():].strip()
    if not title:
        raise ValueError(f"requirement heading has no title: {text!r}")
    return title, version


def parse_release_plan(text: str) -> ReleasePlan:
    """Parse a Markdown milestone plan.

    Format (headings are the contract)::

        # 发布计划：<plan title>

        ## 里程碑 M1：基础可用
        ### 需求 R1：待办管理 [v0.1.0]
        <requirement text>

        ## 里程碑 M2：增强
        ### 需求 R2：标签
        <requirement text>

    ``## `` starts a milestone, ``### `` starts a requirement and its body
    runs until the next requirement/milestone heading. The optional
    ``[vX.Y.Z]`` suffix pins that delivery's release version; without it the
    release phase auto-bumps from the deliverable's ``release_log.json``.
    """
    if not isinstance(text, str):
        raise TypeError("release plan text must be a string")
    document = text.lstrip("\ufeff")
    if not document.strip():
        raise ValueError("release plan is empty")

    title = PLAN_TITLE_DEFAULT
    title_seen = False
    milestones: list[str] = []
    entries: list[ReleasePlanEntry] = []
    current_milestone: str | None = None
    current_title: str | None = None
    current_version: str | None = None
    current_body: list[str] = []

    def finish() -> None:
        nonlocal current_title, current_version, current_body
        if current_title is None:
            return
        requirement = "\n".join(current_body).strip()
        if not requirement:
            raise ValueError(f"requirement {current_title!r} has an empty body")
        if current_milestone is None:
            raise ValueError(f"requirement {current_title!r} must belong to a milestone")
        entries.append(
            ReleasePlanEntry(
                index=len(entries) + 1,
                milestone=current_milestone,
                title=current_title,
                requirement=requirement,
                version=current_version,
            )
        )
        current_title = None
        current_version = None
        current_body = []

    for raw_line in document.splitlines():
        line = raw_line.rstrip()
        if line.startswith("### "):
            finish()
            if current_milestone is None:
                raise ValueError("a requirement heading must follow a '## 里程碑' heading")
            current_title, current_version = _parse_requirement_heading(line[4:])
            continue
        if line.startswith("## "):
            finish()
            current_milestone = _normalize_milestone(line[3:])
            milestones.append(current_milestone)
            continue
        if line.startswith("# ") and not title_seen:
            title = line[2:].strip() or PLAN_TITLE_DEFAULT
            title_seen = True
            continue
        if current_title is not None:
            current_body.append(line)
    finish()

    if not entries:
        raise ValueError("release plan must define at least one requirement ('### ...')")
    if len(milestones) != len(set(milestones)):
        raise ValueError("release plan repeats a milestone label")
    return ReleasePlan(title=title, entries=tuple(entries))


def _outcome_release_line(outcome: dict[str, Any]) -> str:
    release = outcome.get("release")
    if not isinstance(release, dict):
        return "- 发布：未请求"
    status = release.get("status")
    if status == "released":
        return (
            f"- 发布：released v{release.get('version')}"
            f"（tag {release.get('tag')}，commit {str(release.get('commit'))[:12]}）"
        )
    if status == "pending":
        return f"- 发布：待确认（v{release.get('version')}，未写发布记录）"
    if status == "blocked":
        return f"- 发布：已门禁（{release.get('reason')}）"
    if status == "failed":
        return f"- 发布：失败（{release.get('error')}）"
    return f"- 发布：{status or '无记录'}"


def render_release_plan(
    plan: ReleasePlan,
    outcomes: list[dict[str, Any]],
    *,
    now: datetime | str | None = None,
) -> str:
    """Render the shared plan document with one section per milestone."""
    if not isinstance(plan, ReleasePlan):
        raise TypeError("plan must be a ReleasePlan")
    if not isinstance(outcomes, list):
        raise TypeError("outcomes must be a list")
    created_at = _timestamp(now)
    by_index: dict[int, dict[str, Any]] = {
        outcome["index"]: outcome
        for outcome in outcomes
        if isinstance(outcome, dict) and isinstance(outcome.get("index"), int)
    }
    completed = sum(
        1 for outcome in by_index.values() if outcome.get("status") == "completed"
    )
    lines = [
        f"# {plan.title}",
        "",
        f"- 生成时间：{created_at}",
        f"- 需求条目：{len(plan.entries)}",
        f"- 里程碑：{', '.join(plan.milestones)}",
        f"- 执行结果：完成 {completed} / 总计 {len(plan.entries)}",
        "",
    ]
    for milestone in plan.milestones:
        lines.append(f"## 里程碑 {milestone}")
        for entry in plan.entries_for(milestone):
            outcome = by_index.get(entry.index, {})
            lines.append(f"### {entry.index}. {entry.title}")
            summary = entry.requirement.splitlines()[0].strip()
            lines.append(f"- 需求摘要：{_truncate(summary, 200)}")
            lines.append(f"- 交付状态：{outcome.get('status', 'pending')}")
            verdict = outcome.get("acceptance_verdict")
            lines.append(f"- 验收结论：{str(verdict).upper() if verdict else '未执行'}")
            lines.append(_outcome_release_line(outcome))
            if outcome.get("deliverable_root"):
                lines.append(f"- 交付目录：{outcome['deliverable_root']}")
            if outcome.get("error"):
                lines.append(f"- 错误：{outcome['error']}")
            lines.append("")
    return "\n".join(lines)


def write_release_plan(
    plan: ReleasePlan,
    outcomes: list[dict[str, Any]],
    output_path: str | Path,
    *,
    now: datetime | str | None = None,
) -> Path:
    """Write the shared plan document and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_release_plan(plan, outcomes, now=now), encoding="utf-8")
    return path


def collect_release_history(
    root: str | Path,
    *,
    max_depth: int = DEFAULT_HISTORY_DEPTH,
) -> list[dict[str, Any]]:
    """Aggregate every ``release_log.json`` under ``root`` into one history.

    Hidden and runtime-cache directories are pruned; traversal is bounded by
    ``max_depth`` (0 means "only the root itself"). A corrupt log fails closed
    rather than silently dropping a release from the history.
    """
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0:
        raise ValueError("max_depth must be a non-negative integer")
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"release history root does not exist: {root_path}")
    root_path = root_path.resolve()
    base_depth = len(root_path.parts)
    records: list[dict[str, Any]] = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        depth = len(Path(dirpath).parts) - base_depth
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and name not in _HISTORY_SKIP_DIRS
        )
        if depth >= max_depth:
            dirnames[:] = []
        if RELEASE_LOG_FILENAME not in filenames:
            continue
        deliverable_path = Path(dirpath)
        try:
            relative = deliverable_path.relative_to(root_path)
        except ValueError:
            relative = Path(".")
        deliverable = "." if relative == Path(".") else relative.as_posix()
        for entry in load_release_log(deliverable_path):
            records.append(
                {
                    "deliverable": deliverable,
                    **{
                        key: entry.get(key)
                        for key in (
                            "project",
                            "version",
                            "tag",
                            "commit",
                            "created_at",
                            "acceptance_verdict",
                            "integration_status",
                            "milestone",
                        )
                    },
                }
            )

    records.sort(
        key=lambda record: (
            str(record.get("created_at") or ""),
            _version_sort_key(record.get("version")),
            str(record.get("deliverable") or ""),
        )
    )
    return records


def render_release_history(records: list[dict[str, Any]]) -> str:
    """Render aggregated release history as a deterministic Markdown table."""
    if not isinstance(records, list):
        raise TypeError("records must be a list")
    header = "| 交付目录 | 版本 | Tag | 发布时间 | 验收 | 里程碑 |"
    divider = "|---|---|---|---|---|---|"
    lines = [header, divider]
    for record in records:
        lines.append(
            "| {deliverable} | {version} | {tag} | {created_at} | {acceptance} | {milestone} |".format(
                deliverable=record.get("deliverable") or ".",
                version=record.get("version") or "",
                tag=record.get("tag") or "",
                created_at=record.get("created_at") or "",
                acceptance=str(record.get("acceptance_verdict") or "").upper(),
                milestone=record.get("milestone") or "",
            )
        )
    if not records:
        lines.append("| （无发布记录） |  |  |  |  |  |")
    return "\n".join(lines)


def _version_sort_key(version: Any) -> tuple[int, ...]:
    core = str(version or "").split("+")[0].split("-")[0]
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return (0,)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _timestamp(now: datetime | str | None) -> str:
    if isinstance(now, str):
        return now
    moment = now or datetime.now(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def load_release_plan_file(path: str | Path) -> ReleasePlan:
    """Read and parse a plan file as UTF-8, rejecting an empty document."""
    document = Path(path).read_text(encoding="utf-8")
    if not document.strip():
        raise ValueError("release plan file is empty")
    return parse_release_plan(document)


def plan_summary(plan: ReleasePlan) -> dict[str, Any]:
    """Host-owned metadata for JSON output (no raw requirement prompts)."""
    return {
        "title": plan.title,
        "milestones": list(plan.milestones),
        "requirements": [
            {
                "index": entry.index,
                "milestone": entry.milestone,
                "title": entry.title,
                "version": entry.version,
            }
            for entry in plan.entries
        ],
    }
