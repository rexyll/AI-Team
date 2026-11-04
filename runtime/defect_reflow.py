"""Standardized defect intake and hotfix reflow.

A customer reports defects in a small deterministic Markdown format; this
module validates that intake, checks the declared versions against the
deliverable's release history, turns each accepted defect into a hotfix
developer/verification task, and writes two artifacts:

- ``hotfix_request.md`` — the same defect set expressed as customer change
  requests (``CHG-xxx``), so the regular ``--change-request`` path can also
  consume it;
- ``docs/defect_report.md`` — the defect-to-hotfix-task-to-version mapping and
  the (re)packaging outcome.

Intake format::

    ## 缺陷 DEF-001 登录后立即退出
    - 严重级别: 严重
    - 影响版本: v0.1.0
    - 描述: 输入正确凭据后进程退出。
    - 复现步骤: 运行 login 命令，输入 admin/admin。

``严重级别`` and ``描述`` are required; ``影响版本`` defaults to the latest
released version and, when present, must exist in the release history
(fail-closed against typos). Severities accept 致命/严重/一般/轻微 (or their
English equivalents). Defect content is customer input and is fenced with the
untrusted-data boundary before it reaches a developer prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.release import load_release_log, resolve_version, validate_semver
from runtime.task_validator import validate_plan
from security.prompt_injection import untrusted_content

DEFECT_REPORT_RELATIVE_PATH = "docs/defect_report.md"
HOTFIX_REQUEST_FILENAME = "hotfix_request.md"
DEFECT_STATUS_VALUES = ("prepared", "fixed", "pending", "failed")

SEVERITY_LABELS = {
    "critical": "致命",
    "major": "严重",
    "minor": "一般",
    "trivial": "轻微",
}
_SEVERITY_ALIASES = {
    "致命": "critical",
    "critical": "critical",
    "严重": "major",
    "major": "major",
    "一般": "minor",
    "minor": "minor",
    "轻微": "trivial",
    "trivial": "trivial",
}
_DEFECT_HEADING = re.compile(r"^##\s+(?:缺陷\s+)?(DEF-\d{3,})\s+(.+)$")
_DEFECT_ID = re.compile(r"^DEF-\d{3,}$")
_FIELD = re.compile(r"^-\s*([^：:]+)[：:]\s*(.*)$")
_ALLOWED_FIELDS = ("严重级别", "影响版本", "描述", "复现步骤")


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _normalize_version(value: str) -> str:
    text = _require_text("version", value)
    if text.lower().startswith("v") and len(text) > 1:
        text = text[1:].strip()
    return validate_semver(text)


def _timestamp(now: datetime | str | None) -> str:
    if isinstance(now, str):
        return now
    moment = now or datetime.now(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Defect:
    """One validated customer defect."""

    defect_id: str
    title: str
    severity: str
    description: str
    affected_version: str | None = None
    reproduction: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.defect_id, str) or not _DEFECT_ID.match(self.defect_id):
            raise ValueError(f"defect id must look like DEF-001, got {self.defect_id!r}")
        _require_text("defect title", self.title)
        if self.severity not in SEVERITY_LABELS:
            raise ValueError(
                "severity must be one of " + ", ".join(SEVERITY_LABELS) + f", got {self.severity!r}"
            )
        _require_text("defect description", self.description)
        if self.affected_version is not None:
            _normalize_version(self.affected_version)
        if self.reproduction is not None and not isinstance(self.reproduction, str):
            raise TypeError("reproduction must be a string or None")

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABELS[self.severity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.defect_id,
            "title": self.title,
            "severity": self.severity,
            "severity_label": self.severity_label,
            "description": self.description,
            "affected_version": self.affected_version,
            "reproduction": self.reproduction,
        }


@dataclass(frozen=True)
class HotfixPreparation:
    """Validated defect set plus the deterministic hotfix plan."""

    project: str
    deliverable_root: str
    baseline_version: str
    hotfix_version: str
    defects: tuple[Defect, ...]
    plan: dict[str, Any]
    change_request: str

    def __post_init__(self) -> None:
        _require_text("project", self.project)
        _require_text("deliverable_root", self.deliverable_root)
        validate_semver(self.baseline_version)
        validate_semver(self.hotfix_version)
        if not self.defects:
            raise ValueError("hotfix preparation requires at least one defect")
        if not isinstance(self.defects, tuple):
            raise TypeError("defects must be a tuple")
        if not isinstance(self.plan, dict):
            raise TypeError("plan must be a dictionary")
        if not isinstance(self.change_request, str) or not self.change_request.strip():
            raise ValueError("change_request must be a non-empty string")


def parse_defect_intake(text: str) -> list[Defect]:
    """Parse and validate the customer defect file (strict, deterministic).

    Raises ``ValueError`` with the offending defect id/line when a required
    field is missing, a field is unknown, or ids repeat.
    """
    if not isinstance(text, str):
        raise TypeError("defect intake text must be a string")
    defects: list[Defect] = []
    seen_ids: set[str] = set()

    current: dict[str, str] | None = None
    current_id: str | None = None
    current_title: str | None = None
    last_field: str | None = None
    started_at_line: int = 0

    def finish() -> None:
        nonlocal current, current_id, current_title, last_field
        if current is None or current_id is None:
            return
        missing = [name for name in ("严重级别", "描述") if not current.get(name, "").strip()]
        if missing:
            raise ValueError(
                f"缺陷 {current_id}（第 {started_at_line} 行起）缺少字段：" + "、".join(missing)
            )
        severity_raw = current["严重级别"].strip()
        severity = _SEVERITY_ALIASES.get(severity_raw.casefold().strip()) or _SEVERITY_ALIASES.get(
            severity_raw.strip()
        )
        if severity is None:
            raise ValueError(
                f"缺陷 {current_id} 的严重级别非法：{severity_raw!r}"
                "（可用 致命/严重/一般/轻微）"
            )
        affected = current.get("影响版本", "").strip() or None
        if affected is not None:
            affected = _normalize_version(affected)
        reproduction = current.get("复现步骤", "").strip() or None
        defects.append(
            Defect(
                defect_id=current_id,
                title=current_title or "",
                severity=severity,
                description=current["描述"].strip(),
                affected_version=affected,
                reproduction=reproduction,
            )
        )
        current = None
        current_id = None
        current_title = None
        last_field = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            finish()
            heading = line[3:].strip()
            if heading.startswith("缺陷") or heading.startswith("DEF-"):
                match = _DEFECT_HEADING.match(line)
                if match is None:
                    raise ValueError(
                        f"缺陷标题格式非法（第 {line_no} 行）：应为 '## 缺陷 DEF-001 标题'"
                    )
                defect_id = match.group(1)
                title = match.group(2).strip()
                if defect_id in seen_ids:
                    raise ValueError(f"缺陷编号重复：{defect_id}")
                seen_ids.add(defect_id)
                current = {}
                current_id = defect_id
                current_title = title
                started_at_line = line_no
            # Other '## ' sections are document structure and end the section.
            continue
        if current is None:
            continue
        if line.startswith("#"):
            raise ValueError(f"缺陷 {current_id} 内出现非法标题（第 {line_no} 行）：{line}")
        match = _FIELD.match(line)
        if match is not None:
            key = match.group(1).strip()
            if key not in _ALLOWED_FIELDS:
                raise ValueError(
                    f"缺陷 {current_id} 含未知字段 {key!r}（第 {line_no} 行）"
                    f"；允许字段：{'、'.join(_ALLOWED_FIELDS)}"
                )
            if key in current:
                raise ValueError(f"缺陷 {current_id} 字段重复：{key}（第 {line_no} 行）")
            current[key] = match.group(2).strip()
            last_field = key
            continue
        if last_field is None:
            raise ValueError(f"缺陷 {current_id} 出现无法识别的内容（第 {line_no} 行）：{line}")
        # Indented/plain continuation lines extend the previous field.
        current[last_field] = f"{current[last_field]}\n{line}".strip()

    finish()
    if not defects:
        raise ValueError("缺陷清单为空：未找到任何 '## 缺陷 DEF-xxx 标题' 段落")
    return defects


def load_defect_intake(path: str | Path) -> list[Defect]:
    """Load a UTF-8 defect intake file; empty files are rejected."""
    document = Path(path).read_text(encoding="utf-8")
    if not document.strip():
        raise ValueError("defect intake file cannot be empty")
    return parse_defect_intake(document)


def _defect_details(defect: Defect, *, baseline_version: str) -> str:
    lines = [
        f"缺陷编号：{defect.defect_id}",
        f"标题：{defect.title}",
        f"严重级别：{defect.severity_label}",
        f"影响版本：v{defect.affected_version or baseline_version}",
        f"描述：{defect.description}",
    ]
    if defect.reproduction:
        lines.append(f"复现步骤：{defect.reproduction}")
    return "\n".join(lines)


def build_hotfix_plan(
    *,
    project: str,
    defects: list[Defect] | tuple[Defect, ...],
    baseline_version: str,
    hotfix_version: str,
) -> dict[str, Any]:
    """Build a validated plan: one fix + one verification task per defect."""
    _require_text("project", project)
    validate_semver(baseline_version)
    validate_semver(hotfix_version)
    prepared = list(defects)
    if not prepared:
        raise ValueError("hotfix plan requires at least one defect")

    tasks: list[dict[str, Any]] = []
    verify_ids: list[str] = []
    for defect in prepared:
        fix_id = f"{defect.defect_id}-FIX"
        verify_id = f"{defect.defect_id}-VERIFY"
        details = _defect_details(defect, baseline_version=baseline_version)
        tasks.append({
            "id": fix_id,
            "title": f"修复 {defect.defect_id}：{defect.title}",
            "description": (
                f"按客户缺陷清单修复交付缺陷 {defect.defect_id}"
                f"（{defect.severity_label}，基线 v{baseline_version}）。"
                "要求：定位根因并修复；补充覆盖该缺陷的回归测试；"
                "不得删除或弱化既有测试断言。\n\n"
                + untrusted_content("customer.defect_intake", details)
            ),
            "role": "developer",
            "dependencies": [],
        })
        tasks.append({
            "id": verify_id,
            "title": f"回归验证 {defect.defect_id}",
            "description": (
                f"独立验证缺陷 {defect.defect_id} 的修复：确认缺陷不可复现、"
                "全量测试通过，并给出 TEST_PASSED/TEST_FAILED 证据；"
                "不得仅复述开发者的结论。"
            ),
            "role": "tester",
            "dependencies": [fix_id],
        })
        verify_ids.append(verify_id)

    tasks.append({
        "id": "HOTFIX-REVIEW",
        "title": f"审核热修 v{hotfix_version}",
        "description": (
            f"审核热修版本 v{hotfix_version}（基于 v{baseline_version}）："
            f"确认 {len(prepared)} 个缺陷的修复与验证任务都已完成，"
            "测试未被削弱，可以进入集成回归与重新打包。"
        ),
        "role": "reviewer",
        "dependencies": verify_ids,
    })

    plan = {
        "project": project,
        "summary": (
            f"热修 v{hotfix_version}：修复 {len(prepared)} 个客户缺陷"
            f"（{', '.join(defect.defect_id for defect in prepared)}），基于 v{baseline_version}。"
        ),
        "tasks": tasks,
    }
    validate_plan(plan)
    return plan


def build_hotfix_change_request(
    *,
    defects: list[Defect] | tuple[Defect, ...],
    baseline_version: str,
    hotfix_version: str,
) -> str:
    """Render the defect set as CHG-xxx amendments for the analyst path."""
    prepared = list(defects)
    if not prepared:
        raise ValueError("hotfix change request requires at least one defect")
    validate_semver(baseline_version)
    validate_semver(hotfix_version)
    lines = [
        f"# 热修变更请求（缺陷回流，{len(prepared)} 项）",
        "",
        f"- 基线版本：v{baseline_version}",
        f"- 目标版本：v{hotfix_version}",
        "",
    ]
    for index, defect in enumerate(prepared, start=1):
        lines.append(f"变更 {index}（CHG-{index:03d}）：修复 {defect.defect_id} {defect.title}")
        lines.append(f"- 严重级别：{defect.severity_label}")
        lines.append(f"- 影响版本：v{defect.affected_version or baseline_version}")
        lines.append(f"- 描述：{defect.description}")
        if defect.reproduction:
            lines.append(f"- 复现步骤：{defect.reproduction}")
        lines.append("- 验收标准：该缺陷不可复现，且产品级全量回归通过。")
        lines.append("")
    return "\n".join(lines)


def prepare_hotfix(
    deliverable_root: str | Path,
    intake_text: str,
    *,
    hotfix_version: str | None = None,
) -> HotfixPreparation:
    """Validate intake against release history and build the hotfix plan.

    A hotfix requires a previously released deliverable: without a release log
    there is no baseline version to patch and no rollback anchor.
    """
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError(f"deliverable root does not exist: {root}")
    released = load_release_log(root)
    if not released:
        raise ValueError(
            f"热修需要已发布的交付物（{root} 缺少 release_log.json 记录）"
            "；请先以 --release 完成一次发布"
        )
    baseline_version = _normalize_version(
        _require_text("released version", released[-1].get("version"))
    )
    defects = parse_defect_intake(intake_text)
    released_versions = {
        entry["version"] for entry in released if isinstance(entry.get("version"), str)
    }
    for defect in defects:
        if defect.affected_version is not None and defect.affected_version not in released_versions:
            raise ValueError(
                f"缺陷 {defect.defect_id} 的影响版本 v{defect.affected_version} "
                f"不在发布历史中（已发布：{', '.join(sorted(released_versions)) or '无'}）"
            )
    target_version = resolve_version(root, hotfix_version, released)
    project_value = released[-1].get("project")
    project = project_value.strip() if isinstance(project_value, str) and project_value.strip() else root.name
    plan = build_hotfix_plan(
        project=project,
        defects=defects,
        baseline_version=baseline_version,
        hotfix_version=target_version,
    )
    change_request = build_hotfix_change_request(
        defects=defects,
        baseline_version=baseline_version,
        hotfix_version=target_version,
    )
    return HotfixPreparation(
        project=project,
        deliverable_root=str(root),
        baseline_version=baseline_version,
        hotfix_version=target_version,
        defects=tuple(defects),
        plan=plan,
        change_request=change_request,
    )


_STATUS_LABELS = {
    "prepared": "PREPARED（已生成热修计划，尚未执行）",
    "fixed": "FIXED（已修复并重新打包）",
    "pending": "PENDING（等待发布确认）",
    "failed": "FAILED（热修未完成）",
}
_TASK_STATUS_LABELS = {
    "prepared": "待执行",
    "fixed": "已修复",
    "pending": "待确认",
    "failed": "未完成",
}


def _render_report(
    preparation: HotfixPreparation,
    *,
    status: str,
    delivery: dict[str, Any] | None,
    error: str | None,
    now: datetime | str | None,
) -> str:
    release = delivery.get("release") if isinstance(delivery, dict) else None
    integration = delivery.get("integration") if isinstance(delivery, dict) else None
    acceptance = delivery.get("acceptance") if isinstance(delivery, dict) else None
    package = delivery.get("package") if isinstance(delivery, dict) else None
    released_version = (
        release.get("version")
        if isinstance(release, dict) and release.get("status") == "released"
        else None
    )
    lines = [
        "# 缺陷处理报告（Defect Reflow Report）",
        "",
        f"- 项目：{preparation.project}",
        f"- 交付目录：{preparation.deliverable_root}",
        f"- 基线版本：v{preparation.baseline_version}",
        f"- 热修目标版本：v{released_version or preparation.hotfix_version}",
        f"- 处理状态：{_STATUS_LABELS[status]}",
        f"- 生成时间：{_timestamp(now)}",
        "",
        "## 缺陷→热修任务映射",
        "",
        "| 缺陷 | 严重级别 | 标题 | 修复任务 | 验证任务 | 状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    task_label = _TASK_STATUS_LABELS[status]
    for defect in preparation.defects:
        lines.append(
            f"| {defect.defect_id} | {defect.severity_label} | {defect.title} "
            f"| {defect.defect_id}-FIX | {defect.defect_id}-VERIFY | {task_label} |"
        )
    lines += ["", "## 验证与重新打包", ""]
    if isinstance(integration, dict):
        lines.append(
            f"- 集成回归：{integration.get('status')}（修复轮次 {integration.get('rounds', 0)}）"
        )
    else:
        lines.append("- 集成回归：未执行")
    if isinstance(acceptance, dict) and acceptance.get("verdict"):
        lines.append(f"- 需求验收：{str(acceptance['verdict']).upper()}")
    elif isinstance(delivery, dict):
        lines.append("- 需求验收：无结构化需求编号，未执行")
    qa = delivery.get("qa") if isinstance(delivery, dict) else None
    if isinstance(qa, dict) and qa.get("verdict"):
        lines.append(f"- QA 对抗测试：{qa['verdict']}")
    if isinstance(release, dict):
        lines.append(f"- 发布状态：{release.get('status')}（版本 v{release.get('version')}）")
    if isinstance(package, dict):
        lines.append(f"- 交付包：{package.get('archive')}（SHA-256 {package.get('checksum')}）")
    else:
        lines.append("- 交付包：未生成")
    if error:
        lines += ["", "## 失败原因", "", f"- {error}"]
    if status == "prepared":
        lines += [
            "",
            "## 下一步",
            "",
            "```text",
            f"python main.py --hotfix-project {preparation.deliverable_root} "
            "--defect-intake defects.md --auto-release",
            "```",
        ]
    lines += [
        "",
        "## 说明",
        "",
        "- 热修任务由缺陷清单确定性生成；修复不得删除或弱化既有测试断言。",
        "- 缺陷清单原文同时以 CHG-xxx 变更请求写入 hotfix_request.md，可按常规变更流程复用。",
        "",
    ]
    return "\n".join(lines)


def write_hotfix_artifacts(
    preparation: HotfixPreparation,
    *,
    status: str,
    delivery: dict[str, Any] | None = None,
    error: str | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Write ``hotfix_request.md`` and ``docs/defect_report.md``."""
    if status not in DEFECT_STATUS_VALUES:
        raise ValueError(
            f"status must be one of {', '.join(DEFECT_STATUS_VALUES)}, got {status!r}"
        )
    if error is not None and not isinstance(error, str):
        raise TypeError("error must be a string or None")
    root = Path(preparation.deliverable_root)
    if not root.is_dir():
        raise ValueError(f"deliverable root does not exist: {root}")

    request_path = root / HOTFIX_REQUEST_FILENAME
    request_path.write_text(preparation.change_request, encoding="utf-8")
    report_path = root / DEFECT_REPORT_RELATIVE_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(preparation, status=status, delivery=delivery, error=error, now=now),
        encoding="utf-8",
    )
    return {
        "status": status,
        "change_request": str(request_path),
        "report": str(report_path),
    }
