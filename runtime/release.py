"""Release phase: version resolution, release notes, git anchor, release log.

Borrowing OpenClaw's tiered approval design: verification and packaging run
automatically, but the release action pauses for explicit confirmation unless
auto-release is requested (``auto_release=True``) — an unconfirmed release is
recorded as ``pending`` and writes nothing.

The git anchor uses ONLY the host-owned Git boundary
(``HostGitOperationService``): ``git init`` when the deliverable is not yet a
repository, a single release commit, and a ``v<version>`` tag. No push, no
remote, no agent-visible raw git. The release is anchored in the deliverable's
own repository so a customer can audit and roll back by tag.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime.host_git import HostGitOperationService

RELEASE_NOTES_FILENAME = "RELEASE_NOTES.md"
RELEASE_LOG_FILENAME = "release_log.json"
RELEASE_CONFIRM_PROMPT = "确认发布 {project} v{version}? [y/N] "
DEFAULT_RELEASE_VERSION = "0.1.0"
RELEASE_IDENTITY_FALLBACK = {
    "GIT_AUTHOR_NAME": "AI-Team Release",
    "GIT_COMMITTER_NAME": "AI-Team Release",
    "GIT_AUTHOR_EMAIL": "ai-team@local",
    "GIT_COMMITTER_EMAIL": "ai-team@local",
}
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?(?:\+[0-9A-Za-z.\-]+)?$")
_MAX_VERSION_RESOLUTION_STEPS = 100

Confirmer = Callable[[str], bool]


def validate_semver(version: str) -> str:
    """Validate a strict ``MAJOR.MINOR.PATCH`` (optional prerelease/build) version."""
    if not isinstance(version, str) or not _VERSION_PATTERN.match(version.strip()):
        raise ValueError(
            f"release version must be MAJOR.MINOR.PATCH semver, got: {version!r}"
        )
    return version.strip()


def load_release_log(deliverable_root: str | Path) -> list[dict[str, Any]]:
    """Load prior release entries from the deliverable's release log.

    A missing log means no releases yet; a corrupt log fails closed so a
    release can never silently overwrite release history.
    """
    log_path = Path(deliverable_root) / RELEASE_LOG_FILENAME
    if not log_path.is_file():
        return []
    document = json.loads(log_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("releases"), list):
        raise ValueError(f"release log has an unexpected structure: {log_path}")
    return [entry for entry in document["releases"] if isinstance(entry, dict)]


def next_version(last_version: str | None) -> str:
    """Bump the patch component of the last release version (default 0.1.0)."""
    if last_version is None:
        return DEFAULT_RELEASE_VERSION
    core = validate_semver(last_version).split("+")[0].split("-")[0]
    major, minor, patch = (int(part) for part in core.split("."))
    return f"{major}.{minor}.{patch + 1}"


def resolve_version(
    deliverable_root: str | Path,
    explicit_version: str | None,
    released: list[dict[str, Any]],
) -> str:
    """Pick the release version: explicit semver wins; otherwise auto-bump."""
    released_versions = {
        entry.get("version") for entry in released if isinstance(entry.get("version"), str)
    }
    if explicit_version is not None:
        version = validate_semver(explicit_version)
        if version in released_versions:
            raise ValueError(f"release version {version} has already been released")
        return version
    version = next_version(released[-1].get("version") if released else None)
    steps = 0
    while version in released_versions:
        if steps >= _MAX_VERSION_RESOLUTION_STEPS:
            raise ValueError("unable to resolve a fresh release version")
        version = next_version(version)
        steps += 1
    return version


@dataclass(frozen=True)
class ReleaseRequest:
    """Explicit, host-owned release request for one deliverable."""

    deliverable_root: str
    project: str | None = None
    version: str | None = None
    auto_release: bool = False
    confirmer: Confirmer | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.deliverable_root, str) or not self.deliverable_root.strip():
            raise ValueError("deliverable_root must be a non-empty string")
        if self.version is not None and not isinstance(self.version, str):
            raise TypeError("version must be a semver string or None")
        if not isinstance(self.auto_release, bool):
            raise TypeError("auto_release must be a bool")
        if self.confirmer is not None and not callable(self.confirmer):
            raise TypeError("confirmer must be callable or None")


def _terminal_confirmer(prompt: str) -> bool:
    """Interactive confirmation; non-interactive sessions never release."""
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def _clean(output: str) -> str:
    """Strip the ``exit_code=N`` prefix line from a git boundary result."""
    _, _, remainder = output.partition("\n")
    return remainder


def _commit_with_identity_fallback(
    git_service: HostGitOperationService, workspace: str, message: str
) -> str:
    """Commit, retrying once with a local release identity when none exists."""
    result = git_service.commit(workspace, message)
    if result.startswith("exit_code=0"):
        return result
    lowered = result.lower()
    if "identity" in lowered or "user.name" in lowered or "user.email" in lowered:
        env = dict(os.environ)
        for key, value in RELEASE_IDENTITY_FALLBACK.items():
            env.setdefault(key, value)
        retry = git_service.commit(workspace, message, env=env)
        if retry.startswith("exit_code=0"):
            return retry
        raise ValueError(f"release commit failed: {_clean(retry).strip()[:400]}")
    raise ValueError(f"release commit failed: {_clean(result).strip()[:400]}")


def _commit_sha(git_service: HostGitOperationService, workspace: str) -> str:
    try:
        return git_service.head_commit(workspace)
    except ValueError as exc:
        raise ValueError(f"release anchor could not read HEAD: {exc}") from exc


def build_release_notes(
    *,
    project: str | None,
    version: str,
    created_at: str,
    context: dict[str, Any],
) -> str:
    """Render deterministic release notes from verified delivery context."""
    lines = [
        f"# {project or 'AI-Team 交付'} 发布说明（v{version}）",
        "",
        f"- 发布时间：{created_at}",
        f"- 交付目录：{context.get('deliverable_dir') or '.'}",
        "",
        "## 需求与验收",
    ]
    entries = context.get("requirement_entries") or []
    if entries:
        lines.append("### 需求清单")
        for entry in entries:
            if isinstance(entry, dict):
                lines.append(
                    f"- {entry.get('id', '?')} {entry.get('title', '')}"
                    f"（{entry.get('priority', '')}）"
                )
    else:
        lines.append("- （无结构化需求编号）")
    acceptance = context.get("acceptance")
    verdict = (acceptance or {}).get("verdict") if isinstance(acceptance, dict) else None
    lines.append(f"- 验收结论：{str(verdict).upper() if verdict else '未执行'}")
    lines.append("")
    lines.append("## 集成回归")
    integration = context.get("integration")
    if isinstance(integration, dict):
        counts = ""
        summary = integration.get("summary")
        if isinstance(summary, dict) and summary:
            counts = "；结果统计：" + ", ".join(f"{v} {k}" for k, v in summary.items())
        lines.append(
            f"- 状态：{integration.get('status')}；修复轮次：{integration.get('rounds', 0)}{counts}"
        )
        static_status = integration.get("static_status")
        if static_status:
            lines.append(f"- 静态质量门禁：{static_status}")
    else:
        lines.append("- 无集成回归证据")
    qa = context.get("qa")
    if isinstance(qa, dict) and qa.get("verdict"):
        lines.append(f"- QA 对抗测试：{qa.get('verdict')}")
    usage = context.get("usage")
    if isinstance(usage, dict) and usage.get("llm_calls") is not None:
        lines.append(
            f"- 模型用量：输入 {usage.get('input_tokens', 0)} tokens，"
            f"输出 {usage.get('output_tokens', 0)} tokens（{usage.get('llm_calls', 0)} 次调用）"
        )
    lines.append("")
    lines.append("## 交付内容")
    docs = context.get("docs") or []
    if docs:
        lines.append("- 标准文档：" + ", ".join(str(doc) for doc in docs))
    lines.append("- 交付清单：DELIVERY_MANIFEST.md（逐文件 SHA-256）")
    lines.append(
        "- 部署包：与交付目录同级的 delivery zip"
        "（含 install.ps1 / install.sh / Dockerfile / SMOKE_REPORT.md）"
    )
    task_stats = context.get("task_stats")
    if isinstance(task_stats, dict):
        lines.append("")
        lines.append("## 任务统计")
        lines.append(
            f"- 任务总数 {task_stats.get('total', '?')}，完成 {task_stats.get('completed', '?')}"
        )
    lines.append("")
    return "\n".join(lines)


def perform_release(
    request: ReleaseRequest,
    *,
    git_service: HostGitOperationService,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the version, confirm, anchor the deliverable and record the log.

    Returns a detached record: ``released`` (with version/tag/commit/paths),
    or ``pending`` when the confirmation gate was not satisfied — in which
    case nothing is written. Raises on deterministic failures (bad version,
    corrupt log, git boundary errors).
    """
    root = Path(request.deliverable_root)
    if not root.is_dir():
        raise ValueError(f"deliverable root does not exist: {root}")
    released = load_release_log(root)
    version = resolve_version(root, request.version, released)
    project = context.get("project") or request.project or "ai-team-delivery"

    if not request.auto_release:
        confirmer = request.confirmer or _terminal_confirmer
        if not confirmer(RELEASE_CONFIRM_PROMPT.format(project=project, version=version)):
            return {"status": "pending", "version": version, "reason": "release not confirmed"}

    now = context.get("now")
    created_at = (
        now if isinstance(now, str)
        else (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    )
    notes = build_release_notes(
        project=str(project), version=version, created_at=created_at, context=context
    )
    (root / RELEASE_NOTES_FILENAME).write_text(notes, encoding="utf-8")

    workspace = str(root)
    if not git_service.is_repository(workspace):
        git_service.init(workspace)
    status = _clean(git_service.status(workspace))
    if status.strip():
        git_service.add(workspace, ["."])
        _commit_with_identity_fallback(git_service, workspace, f"release: v{version}")
    commit = _commit_sha(git_service, workspace)
    tag_name = f"v{version}"
    git_service.tag(workspace, tag_name, message=f"release {version}")

    integration = context.get("integration")
    acceptance = context.get("acceptance")
    entry = {
        "version": version,
        "tag": tag_name,
        "commit": commit,
        "project": str(project),
        "created_at": created_at,
        "acceptance_verdict": acceptance.get("verdict") if isinstance(acceptance, dict) else None,
        "integration_status": integration.get("status") if isinstance(integration, dict) else None,
        "integration_rounds": integration.get("rounds", 0) if isinstance(integration, dict) else 0,
        "deliverable_dir": context.get("deliverable_dir") or ".",
    }
    released.append(entry)
    log_path = root / RELEASE_LOG_FILENAME
    log_path.write_text(
        json.dumps({"releases": released}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "released",
        "version": version,
        "tag": tag_name,
        "commit": commit,
        "notes": str(root / RELEASE_NOTES_FILENAME),
        "log": str(log_path),
        "project": str(project),
    }
