"""Cross-project knowledge base: durable patterns, pitfalls and conventions.

Every delivery produces evidence (acceptance gaps, integration/rework results,
static-gate and QA verdicts, dependency findings, release facts). This module
turns that evidence into small, deterministic, loadable knowledge entries so a
later project can benefit from earlier deliveries instead of rediscovering the
same failure modes.

Design rules:

- **Deterministic extraction** — entries are derived by fixed rules from a
  delivery record (or, for backfilling, from a finished deliverable's
  ``release_log.json`` plus ``docs/acceptance_report.md``), never by an LLM
  judgment about what a "lesson" is.
- **Stable identity** — an entry id is a hash of (project, kind, title), so
  re-extracting the same delivery is idempotent.
- **Loadable assets** — entries carry kind, tags and target roles; loading is
  filtered by kind/tag/role/keyword and bounded by a limit.
- **Fail-closed persistence** — a corrupt knowledge file raises instead of
  silently dropping accumulated lessons. Extraction failures during a delivery
  are recorded honestly, never fatal to the finished product.
- **Untrusted content** — entries are historical data; callers fence the
  rendered block at the prompt boundary.

Storage layout (default): ``<root>/knowledge_base.json``::

    {"entries": [{"entry_id": ..., "kind": "pitfall", ...}, ...]}
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.process_lock import exclusive_process_lock
from security.secrets import redact_text

KNOWLEDGE_KINDS = ("pattern", "pitfall", "convention")
KNOWLEDGE_KIND_LABELS = {"pattern": "模式", "pitfall": "坑", "convention": "规范"}
KNOWLEDGE_BASE_FILENAME = "knowledge_base.json"
DEFAULT_KNOWLEDGE_LIMIT = 8
_KIND_PRIORITY = {"pitfall": 0, "convention": 1, "pattern": 2}
_REQUIREMENT_ID = re.compile(r"REQ-\d{3,}")
_ACCEPTANCE_VERDICT = re.compile(
    r"验收结论\s*[:：]\s*(?:\*\*)?(PASSED|FAILED)(?:\*\*)?", re.IGNORECASE
)
_MAX_TITLE_CHARS = 100


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _normalized_tuple(name: str, values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise TypeError(f"{name} must be an iterable of strings or None")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} entries must be non-empty strings")
        normalized.append(value.strip())
    return tuple(dict.fromkeys(normalized))


def _timestamp(now: datetime | str | None) -> str:
    if isinstance(now, str):
        return _require_text("created_at", now)
    moment = now or datetime.now(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _truncate(value: str, limit: int = _MAX_TITLE_CHARS) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _requirement_tags(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_REQUIREMENT_ID.findall(text)))


@dataclass(frozen=True)
class KnowledgeEntry:
    """One durable lesson loaded from (or extracted into) the knowledge base."""

    entry_id: str
    kind: str
    title: str
    body: str
    source_project: str
    tags: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    created_at: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("entry_id", self.entry_id)
        if self.kind not in KNOWLEDGE_KINDS:
            raise ValueError(
                f"kind must be one of {', '.join(KNOWLEDGE_KINDS)}, got {self.kind!r}"
            )
        _require_text("title", self.title)
        if not isinstance(self.body, str) or not self.body.strip():
            raise ValueError("body must be a non-empty string")
        _require_text("source_project", self.source_project)
        _require_text("created_at", self.created_at)
        if not isinstance(self.tags, tuple):
            raise TypeError("tags must be a tuple")
        if not isinstance(self.roles, tuple):
            raise TypeError("roles must be a tuple")
        _normalized_tuple("tags", self.tags)
        _normalized_tuple("roles", self.roles)
        if not isinstance(self.evidence, dict):
            raise TypeError("evidence must be a dictionary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "source_project": self.source_project,
            "tags": list(self.tags),
            "roles": list(self.roles),
            "created_at": self.created_at,
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> KnowledgeEntry:
        if not isinstance(payload, dict):
            raise ValueError("knowledge entry must be a dictionary")
        tags = payload.get("tags", [])
        roles = payload.get("roles", [])
        if not isinstance(tags, (list, tuple)) or not isinstance(roles, (list, tuple)):
            raise ValueError("knowledge entry tags/roles must be lists")
        evidence = payload.get("evidence", {})
        if evidence is None:
            evidence = {}
        if not isinstance(evidence, dict):
            raise ValueError("knowledge entry evidence must be a dictionary")
        return cls(
            entry_id=payload.get("entry_id"),
            kind=payload.get("kind"),
            title=payload.get("title"),
            body=payload.get("body"),
            source_project=payload.get("source_project"),
            tags=_normalized_tuple("tags", tags),
            roles=_normalized_tuple("roles", roles),
            created_at=payload.get("created_at"),
            evidence=dict(evidence),
        )


def make_entry_id(kind: str, source_project: str, title: str) -> str:
    """Stable identity derived from the lesson's semantic key."""
    if kind not in KNOWLEDGE_KINDS:
        raise ValueError(f"unknown knowledge kind: {kind!r}")
    project = _require_text("source_project", source_project)
    normalized_title = " ".join(_require_text("title", title).split()).casefold()
    digest = hashlib.sha256(
        f"{project}|{kind}|{normalized_title}".encode("utf-8")
    ).hexdigest()[:10]
    return f"KB-{kind.upper()}-{digest}"


def _build_entry(
    kind: str,
    title: str,
    body: str,
    *,
    project: str,
    tags: Iterable[str] = (),
    roles: Iterable[str] = (),
    created_at: datetime | str | None = None,
    evidence: dict[str, Any] | None = None,
) -> KnowledgeEntry:
    clean_title = _truncate(redact_text(title))
    clean_body = redact_text(body)
    return KnowledgeEntry(
        entry_id=make_entry_id(kind, project, clean_title),
        kind=kind,
        title=clean_title,
        body=clean_body,
        source_project=project,
        tags=_normalized_tuple("tags", tags),
        roles=_normalized_tuple("roles", roles),
        created_at=_timestamp(created_at),
        evidence=evidence or {},
    )


def extract_delivery_knowledge(
    delivery: dict[str, Any],
    *,
    project: str | None = None,
    created_at: datetime | str | None = None,
) -> list[KnowledgeEntry]:
    """Derive deterministic knowledge entries from one delivery record.

    ``delivery`` is the orchestrator's delivery record (acceptance, integration,
    QA, dependency scan, release, docs). Every rule maps concrete evidence to
    one entry; nothing is inferred without evidence. Missing sections simply
    produce no entries.
    """
    if not isinstance(delivery, dict):
        raise TypeError("delivery must be a dictionary")
    if project is None:
        value = delivery.get("project")
        project = value if isinstance(value, str) and value.strip() else None
    project = _require_text("project", project)

    entries: list[KnowledgeEntry] = []

    acceptance = delivery.get("acceptance") if isinstance(delivery.get("acceptance"), dict) else None
    verdict = acceptance.get("verdict") if acceptance else None
    gaps = _string_list(acceptance.get("gaps")) if acceptance else []
    warnings = _string_list(acceptance.get("warnings")) if acceptance else []

    for gap in gaps:
        entries.append(
            _build_entry(
                "pitfall",
                f"验收缺口：{gap}",
                f"交付「{project}」在需求验收中出现缺口：{gap}。"
                "经验：必须级需求在交付前必须同时在需求文档与测试报告中追溯，并逐条给出可验证的验收标准。",
                project=project,
                tags=("acceptance", "gap", *_requirement_tags(gap)),
                roles=("analyst", "developer", "tester", "doc_writer"),
                created_at=created_at,
                evidence={"acceptance_verdict": verdict, "gap": gap},
            )
        )

    for warning in warnings:
        entries.append(
            _build_entry(
                "pitfall",
                f"验收警告：{warning}",
                f"交付「{project}」的需求追溯存在警告：{warning}。"
                "经验：应该/可选级需求虽不判失败，但追溯缺失通常意味着文档或测试证据有遗漏，应在后续交付中补齐。",
                project=project,
                tags=("acceptance", "warning", *_requirement_tags(warning)),
                roles=("analyst", "developer", "doc_writer"),
                created_at=created_at,
                evidence={"acceptance_verdict": verdict, "warning": warning},
            )
        )

    integration = delivery.get("integration") if isinstance(delivery.get("integration"), dict) else None
    if integration is not None:
        status = integration.get("status")
        rounds = integration.get("rounds", 0)
        rounds = rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else 0
        suite = integration.get("suite") if isinstance(integration.get("suite"), dict) else {}
        failed_tests = _string_list(suite.get("failed_tests"))
        if status == "failed":
            test_note = f"，失败用例：{', '.join(failed_tests[:5])}" if failed_tests else ""
            entries.append(
                _build_entry(
                    "pitfall",
                    f"集成回归失败：{rounds} 轮修复后仍未通过",
                    f"交付「{project}」的产品级全量回归在 {rounds} 轮修复后仍失败{test_note}。"
                    "经验：任务级自测通过不等于产品级回归通过；跨模块集成风险必须在打包前用交付物全量测试兜住，"
                    "修复不得通过删除或弱化测试断言来完成。",
                    project=project,
                    tags=("integration", "regression", "failed"),
                    roles=("analyst", "developer", "tester"),
                    created_at=created_at,
                    evidence={"integration_status": status, "rounds": rounds, "failed_tests": failed_tests[:5]},
                )
            )
        elif status == "passed" and rounds > 0:
            entries.append(
                _build_entry(
                    "pitfall",
                    f"集成回归需 {rounds} 轮返工才通过",
                    f"交付「{project}」首轮产品级回归失败，经 {rounds} 轮返工后才通过。"
                    "经验：开发阶段应先运行交付物全量测试并覆盖跨模块接口，再提交集成回归，减少返工轮次。",
                    project=project,
                    tags=("integration", "rework"),
                    roles=("analyst", "developer", "tester"),
                    created_at=created_at,
                    evidence={"integration_status": status, "rounds": rounds},
                )
            )

        static = integration.get("static") if isinstance(integration.get("static"), dict) else None
        if static is not None and static.get("status") == "failed":
            tools = static.get("tools") if isinstance(static.get("tools"), dict) else {}
            failed_tools = [
                name
                for name, record in tools.items()
                if isinstance(record, dict) and record.get("status") == "failed"
            ]
            tool_note = f"（{', '.join(failed_tools)}）" if failed_tools else ""
            entries.append(
                _build_entry(
                    "pitfall",
                    "静态质量门禁未通过" + tool_note,
                    f"交付「{project}」在打包前的静态质量门禁中未通过{tool_note}。"
                    "经验：未定义名称、未使用导入等阻断项必须在开发阶段由静态门禁拦住，"
                    "不得依赖集成回归阶段的返工轮次发现。",
                    project=project,
                    tags=("static", "quality"),
                    roles=("analyst", "developer"),
                    created_at=created_at,
                    evidence={"tools": failed_tools},
                )
            )

    qa = delivery.get("qa") if isinstance(delivery.get("qa"), dict) else None
    if qa is not None and qa.get("verdict") == "QA_FAILED":
        excerpt = _truncate(str(qa.get("message_head") or "").strip(), 200)
        excerpt_note = f"，摘要：{excerpt}" if excerpt else ""
        entries.append(
            _build_entry(
                "pitfall",
                "QA 对抗测试未通过（QA_FAILED）",
                f"交付「{project}」在产品级对抗测试中被判定失败{excerpt_note}。"
                "经验：开发阶段的正常路径测试容易遗漏边界与非法输入、异常路径、重复执行等对抗场景，"
                "应在编写测试时显式覆盖。",
                project=project,
                tags=("qa", "adversarial", "failed"),
                roles=("analyst", "developer", "tester"),
                created_at=created_at,
                evidence={"qa_verdict": qa.get("verdict")},
            )
        )

    scan = delivery.get("dependency_scan") if isinstance(delivery.get("dependency_scan"), dict) else None
    dependency_findings = False
    if scan is not None and scan.get("status") == "completed":
        unpinned = _string_list(scan.get("unpinned"))
        undeclared = _string_list(scan.get("undeclared_imports"))
        dependency_findings = bool(unpinned or undeclared)
        if dependency_findings:
            findings = []
            if unpinned:
                findings.append(f"未钉死版本：{', '.join(unpinned)}")
            if undeclared:
                findings.append(f"未声明的第三方导入：{', '.join(undeclared)}")
            entries.append(
                _build_entry(
                    "pitfall",
                    "依赖声明不完整：未钉死版本或未声明的第三方导入",
                    f"交付「{project}」的依赖清单存在问题：" + "；".join(findings) + "。"
                    "经验：第三方依赖必须在依赖清单中声明并钉死版本，源码中的第三方导入必须与清单一致，"
                    "否则客户环境无法可复现地安装。",
                    project=project,
                    tags=("dependency", "declaration"),
                    roles=("developer", "doc_writer"),
                    created_at=created_at,
                    evidence={"unpinned": unpinned, "undeclared_imports": undeclared},
                )
            )
        elif scan.get("requirements_file") and _string_list(scan.get("declared")):
            entries.append(
                _build_entry(
                    "convention",
                    "依赖声明与导入一致且版本钉死",
                    f"交付「{project}」的第三方依赖全部在依赖清单中声明并钉死版本，"
                    "源码导入与清单一致。规范：依赖清单是交付物的可复现安装契约，新增依赖时同步更新清单并钉死版本。",
                    project=project,
                    tags=("dependency", "convention"),
                    roles=("developer", "doc_writer"),
                    created_at=created_at,
                    evidence={"declared": _string_list(scan.get("declared"))},
                )
            )

    release = delivery.get("release") if isinstance(delivery.get("release"), dict) else None
    released_version = release.get("version") if release and release.get("status") == "released" else None
    if isinstance(released_version, str) and released_version.strip():
        entries.append(
            _build_entry(
                "convention",
                "发布锚点：semver 版本 + git tag + release_log",
                f"交付「{project}」以 v{released_version.strip()} 发布"
                f"（tag {release.get('tag') or 'v' + released_version.strip()}）。"
                "规范：每次发布必须有 semver 版本、交付物 git tag 与 release_log.json 记录，"
                "三者是对客户可追溯、可回滚的版本事实来源。",
                project=project,
                tags=("release", "versioning"),
                roles=("analyst", "developer", "doc_writer"),
                created_at=created_at,
                evidence={"version": released_version, "tag": release.get("tag")},
            )
        )

    qa_ok = qa is None or qa.get("verdict") != "QA_FAILED"
    static_ok = not (
        integration is not None
        and isinstance(integration.get("static"), dict)
        and integration["static"].get("status") == "failed"
    )
    integration_ok = (
        integration is not None
        and integration.get("status") in {"passed", "skipped"}
        and integration.get("rounds", 0) == 0
    )
    if (
        verdict == "passed"
        and integration_ok
        and qa_ok
        and static_ok
        and not dependency_findings
    ):
        version_note = (
            f"（v{released_version.strip()}）"
            if isinstance(released_version, str) and released_version.strip()
            else ""
        )
        docs = delivery.get("docs")
        docs_note = f"，交付文档 {len(docs)} 份" if isinstance(docs, list) and docs else ""
        entries.append(
            _build_entry(
                "pattern",
                "绿色交付基线：验收 / 集成 / 静态 / QA 一次通过",
                f"交付「{project}」{version_note}在首轮即通过需求验收、产品级集成回归、静态质量门禁与 QA 对抗测试"
                f"{docs_note}。模式：以此作为交付达标基线——任何一项未通过都必须修复并重新验证后才能打包发布。",
                project=project,
                tags=("baseline", "delivery"),
                roles=("analyst", "developer", "doc_writer"),
                created_at=created_at,
                evidence={"acceptance_verdict": verdict},
            )
        )

    return entries


def parse_acceptance_report(text: str) -> dict[str, Any]:
    """Parse the deterministic acceptance report into verdict/gaps/warnings."""
    if not isinstance(text, str):
        raise TypeError("acceptance report text must be a string")
    match = _ACCEPTANCE_VERDICT.search(text)
    verdict = match.group(1).lower() if match else None
    gaps: list[str] = []
    warnings: list[str] = []
    section: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading.startswith("验收缺口"):
                section = gaps
            elif heading.startswith("警告"):
                section = warnings
            else:
                section = None
            continue
        if section is not None and line.startswith("- "):
            item = line[2:].strip()
            if item:
                section.append(item)
    return {"verdict": verdict, "gaps": gaps, "warnings": warnings}


def extract_deliverable_knowledge(
    root: str | Path,
    *,
    project: str | None = None,
    created_at: datetime | str | None = None,
) -> list[KnowledgeEntry]:
    """Extract knowledge from an existing deliverable directory (backfill).

    Reads ``release_log.json`` (latest release facts) and
    ``docs/acceptance_report.md`` (verdict, gaps, warnings). A directory with
    neither artifact yields no entries; a corrupt release log fails closed.
    """
    # Local import keeps the runtime release module optional for pure
    # knowledge-base consumers.
    from runtime.release import load_release_log

    base = Path(root)
    if not base.is_dir():
        raise ValueError(f"deliverable root does not exist: {base}")
    try:
        released = load_release_log(base)
    except Exception as exc:
        raise ValueError(f"invalid release log under {base}") from exc
    report_path = base / "docs" / "acceptance_report.md"
    report = (
        parse_acceptance_report(report_path.read_text(encoding="utf-8", errors="replace"))
        if report_path.is_file()
        else None
    )
    if not released and report is None:
        return []

    resolved_project = project
    if resolved_project is None and released:
        value = released[-1].get("project")
        if isinstance(value, str) and value.strip():
            resolved_project = value
    resolved_project = resolved_project or base.name

    acceptance: dict[str, Any] | None = None
    if report is not None:
        acceptance = report
        if acceptance["verdict"] is None and released:
            acceptance = {
                **acceptance,
                "verdict": released[-1].get("acceptance_verdict"),
            }
    elif released and isinstance(released[-1].get("acceptance_verdict"), str):
        acceptance = {
            "verdict": released[-1].get("acceptance_verdict"),
            "gaps": [],
            "warnings": [],
        }

    integration: dict[str, Any] | None = None
    if released and isinstance(released[-1].get("integration_status"), str):
        integration = {
            "status": released[-1].get("integration_status"),
            "rounds": released[-1].get("integration_rounds", 0),
        }

    release = (
        {
            "status": "released",
            "version": released[-1].get("version"),
            "tag": released[-1].get("tag"),
        }
        if released
        else None
    )
    delivery = {
        "acceptance": acceptance,
        "integration": integration,
        "release": release,
        "docs": [],
    }
    return extract_delivery_knowledge(
        delivery, project=resolved_project, created_at=created_at
    )


class KnowledgeBase:
    """File-backed store of cross-project knowledge entries.

    ``path`` may be a ``.json`` file or a directory (the store then lives at
    ``<dir>/knowledge_base.json``). Reads are strict: a corrupt file raises
    instead of silently discarding lessons. Writes are atomic and serialized
    across processes so parallel deliveries cannot lose entries.
    """

    def __init__(self, path: str | Path) -> None:
        if isinstance(path, Path):
            resolved = path
        elif isinstance(path, str) and path.strip():
            resolved = Path(path.strip())
        else:
            raise ValueError("knowledge base path must be a non-empty string or Path")
        if resolved.suffix.lower() == ".json":
            self.path = resolved
        else:
            self.path = resolved / KNOWLEDGE_BASE_FILENAME

    def load(self) -> list[KnowledgeEntry]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid knowledge base: {self.path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            raise ValueError(
                f"knowledge base must contain an 'entries' list: {self.path}"
            )
        try:
            return [KnowledgeEntry.from_dict(item) for item in payload["entries"]]
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"knowledge base contains an invalid entry: {self.path}") from exc

    def add(self, entries: Iterable[KnowledgeEntry]) -> dict[str, int]:
        """Merge entries, deduplicating by stable entry id."""
        if isinstance(entries, KnowledgeEntry):
            raise TypeError("entries must be an iterable of KnowledgeEntry, not one entry")
        prepared = list(entries)
        if any(not isinstance(entry, KnowledgeEntry) for entry in prepared):
            raise TypeError("entries must contain only KnowledgeEntry instances")
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with exclusive_process_lock(lock_path):
            current = self.load()
            known = {entry.entry_id for entry in current}
            added = 0
            duplicates = 0
            for entry in prepared:
                if entry.entry_id in known:
                    duplicates += 1
                    continue
                known.add(entry.entry_id)
                current.append(entry)
                added += 1
            if added:
                self._write(current)
        return {"added": added, "duplicates": duplicates, "total": len(current)}

    def save(self, entries: Iterable[KnowledgeEntry]) -> None:
        """Replace the whole store atomically (host-owned maintenance path)."""
        prepared = list(entries)
        if any(not isinstance(entry, KnowledgeEntry) for entry in prepared):
            raise TypeError("entries must contain only KnowledgeEntry instances")
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with exclusive_process_lock(lock_path):
            self._write(prepared)

    def _write(self, entries: list[KnowledgeEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [entry.to_dict() for entry in entries]}
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.stem}-", suffix=".tmp", dir=self.path.parent, text=True
        )
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def search(
        self,
        *,
        query: str | None = None,
        kinds: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        roles: Iterable[str] | None = None,
        limit: int | None = DEFAULT_KNOWLEDGE_LIMIT,
    ) -> list[KnowledgeEntry]:
        """Filter entries by kind/tag/role/keyword and bound the result."""
        if query is not None and not isinstance(query, str):
            raise TypeError("query must be a string or None")
        normalized_kinds = _normalized_tuple("kinds", kinds)
        unknown = [kind for kind in normalized_kinds if kind not in KNOWLEDGE_KINDS]
        if unknown:
            raise ValueError(f"unknown knowledge kinds: {', '.join(unknown)}")
        normalized_tags = _normalized_tuple("tags", tags)
        normalized_roles = _normalized_tuple("roles", roles)
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer or None")

        tokens = [token.casefold() for token in (query or "").split() if token.strip()]
        selected: list[KnowledgeEntry] = []
        for entry in self.load():
            if normalized_kinds and entry.kind not in normalized_kinds:
                continue
            if normalized_tags and not set(normalized_tags).issubset(set(entry.tags)):
                continue
            if normalized_roles and entry.roles and not set(normalized_roles) & set(entry.roles):
                continue
            if tokens:
                haystack = f"{entry.title} {entry.body} {' '.join(entry.tags)}".casefold()
                if not any(token in haystack for token in tokens):
                    continue
            selected.append(entry)

        # Deterministic ordering: newest first, then stable id; a second
        # stable sort puts the most actionable kind (pitfalls) first.
        selected.sort(key=lambda entry: entry.entry_id)
        selected.sort(key=lambda entry: entry.created_at, reverse=True)
        selected.sort(key=lambda entry: _KIND_PRIORITY[entry.kind])
        if limit is not None:
            selected = selected[:limit]
        return selected


def render_knowledge_prompt(entries: Iterable[KnowledgeEntry]) -> str:
    """Render entries as a compact Markdown block for a prompt context."""
    prepared = list(entries)
    if any(not isinstance(entry, KnowledgeEntry) for entry in prepared):
        raise TypeError("entries must contain only KnowledgeEntry instances")
    if not prepared:
        return ""
    lines = ["### 跨项目知识资产（历史交付沉淀）", ""]
    for entry in prepared:
        label = KNOWLEDGE_KIND_LABELS[entry.kind]
        lines.append(f"- [{label}] {entry.title}（来源：{entry.source_project}）")
        for body_line in entry.body.splitlines():
            lines.append(f"  {body_line}".rstrip())
    return "\n".join(lines)


def render_knowledge_list(entries: Iterable[KnowledgeEntry]) -> str:
    """Render entries as a deterministic Markdown table for CLI output."""
    prepared = list(entries)
    if any(not isinstance(entry, KnowledgeEntry) for entry in prepared):
        raise TypeError("entries must contain only KnowledgeEntry instances")
    lines = [
        "| 编号 | 类型 | 标题 | 来源项目 | 标签 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in prepared:
        lines.append(
            f"| {entry.entry_id} | {KNOWLEDGE_KIND_LABELS[entry.kind]} | {entry.title} "
            f"| {entry.source_project} | {', '.join(entry.tags)} |"
        )
    if not prepared:
        lines.append("| （无知识资产） |  |  |  |  |")
    return "\n".join(lines)


def build_knowledge_prompt(
    path: str | Path | None,
    *,
    roles: Iterable[str] | None = None,
    query: str | None = None,
    kinds: Iterable[str] | None = None,
    limit: int | None = DEFAULT_KNOWLEDGE_LIMIT,
) -> str:
    """Load, filter and render the knowledge base for one consumer.

    Returns ``""`` when the store is disabled (``path`` is None) or no asset
    matches. A corrupt store raises (fail-closed).
    """
    if path is None:
        return ""
    entries = KnowledgeBase(path).search(
        query=query, kinds=kinds, roles=roles, limit=limit
    )
    return render_knowledge_prompt(entries)
