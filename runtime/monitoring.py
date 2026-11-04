"""Post-delivery monitoring contract and deterministic heartbeat checks.

Honest scope: this runtime has no deployment target environment, so it does not
pretend to integrate a cloud APM/alerting service. What it does deliver is a
machine-readable health contract plus an offline heartbeat that verifies the
facts the customer actually received:

- ``release_anchor`` — the deliverable's ``release_log.json`` still records a
  resolvable version/tag/commit;
- ``manifest_integrity`` — every file listed in ``DELIVERY_MANIFEST.md`` exists
  and its SHA-256 still matches;
- ``smoke_suite`` — the delivered test suite still passes from a fresh copy of
  the files (the same isolated-copy mechanism used by packaging smoke).

An operator schedules the heartbeat (cron / Task Scheduler). A non-zero exit
status is the alerting signal; this is documented in ``MONITORING.md`` shipped
inside the deliverable. When monitoring turns red, the defect reflow path
(``--defect-intake``) is the standardized escalation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.deployment import DEFAULT_SMOKE_TIMEOUT, run_smoke_verification
from runtime.release import load_release_log

MONITORING_DIR = "monitoring"
HEALTH_CONTRACT_FILENAME = "health_contract.json"
HEALTH_STATUS_FILENAME = "status.json"
MONITORING_DOC_FILENAME = "MONITORING.md"
MANIFEST_FILENAME = "DELIVERY_MANIFEST.md"

PROBE_RELEASE_ANCHOR = "release_anchor"
PROBE_MANIFEST_INTEGRITY = "manifest_integrity"
PROBE_SMOKE_SUITE = "smoke_suite"

_MANIFEST_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*\d+\s*\|\s*([0-9a-fA-F]{64})\s*\|$")


def _timestamp(now: datetime | str | None) -> str:
    if isinstance(now, str):
        return now
    moment = now or datetime.now(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _release_record(release: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep only the released facts the contract/heartbeat needs."""
    if not isinstance(release, dict) or release.get("status") != "released":
        return None
    version = release.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    return {
        "version": version.strip(),
        "tag": release.get("tag") if isinstance(release.get("tag"), str) else None,
        "commit": release.get("commit") if isinstance(release.get("commit"), str) else None,
    }


def build_monitoring_contract(
    *,
    project: str,
    deliverable_root: str = ".",
    release: dict[str, Any] | None = None,
    created_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build the deterministic monitoring contract for one deliverable."""
    project = _require_text("project", project)
    if not isinstance(deliverable_root, str) or not deliverable_root.strip():
        raise ValueError("deliverable_root must be a non-empty string")
    return {
        "schema_version": 1,
        "project": project,
        "deliverable_root": deliverable_root.strip(),
        "created_at": _timestamp(created_at),
        "release": _release_record(release),
        "probes": [
            {
                "id": PROBE_RELEASE_ANCHOR,
                "kind": "version",
                "severity": "critical",
                "description": "release_log.json 的最新记录包含 version/tag/commit。",
            },
            {
                "id": PROBE_MANIFEST_INTEGRITY,
                "kind": "integrity",
                "severity": "critical",
                "description": "DELIVERY_MANIFEST.md 中每个文件存在且 SHA-256 与清单一致。",
            },
            {
                "id": PROBE_SMOKE_SUITE,
                "kind": "regression",
                "severity": "critical",
                "description": "在独立临时副本中运行交付物的测试套件，验证部署形态仍然可用。",
            },
        ],
        "heartbeat": {
            "command": f"python main.py --monitor-check {deliverable_root.strip()}",
            "status_file": f"{MONITORING_DIR}/{HEALTH_STATUS_FILENAME}",
            "schedule_example": "cron: 0 8 * * * （每日 08:00；也可用 Windows 任务计划程序）",
            "alert_rule": "命令非零退出或 status 不为 healthy 即触发告警。",
        },
        "limitations": (
            "本运行时没有客户部署目标环境，未接入云监控/APM/告警通道；"
            "心跳检测的是交付物自身的版本锚点、清单完整性与回归套件，"
            "外部监控需要客户在部署环境按 MONITORING.md 接入。"
        ),
    }


def render_monitoring_doc(contract: dict[str, Any]) -> str:
    """Render the human-readable monitoring guide shipped with the deliverable."""
    probes = contract.get("probes") or []
    release = contract.get("release") or {}
    release_line = (
        f"v{release.get('version')}（tag {release.get('tag') or '未记录'}）"
        if release
        else "未发布（release 阶段未执行，版本锚点探针将报告 unavailable）"
    )
    heartbeat = contract.get("heartbeat") or {}
    lines = [
        f"# {contract.get('project')} — 交付后监控说明（MONITORING）",
        "",
        f"- 基线版本：{release_line}",
        f"- 监控契约：`{MONITORING_DIR}/{HEALTH_CONTRACT_FILENAME}`",
        "",
        "## 探针",
        "",
        "| 探针 | 类型 | 检查内容 |",
        "| --- | --- | --- |",
    ]
    for probe in probes:
        lines.append(
            f"| {probe.get('id')} | {probe.get('kind')} | {probe.get('description')} |"
        )
    lines += [
        "",
        "## 心跳执行",
        "",
        f"- 命令：`{heartbeat.get('command')}`",
        f"- 建议调度：{heartbeat.get('schedule_example')}",
        f"- 状态文件：`{heartbeat.get('status_file')}`",
        f"- 告警规则：{heartbeat.get('alert_rule')}",
        "",
        "心跳是离线、确定性的自检：不依赖外部服务，输入只有交付目录本身，"
        "因此可以在客户环境复现同一结论。",
        "",
        "## 缺陷回流",
        "",
        "心跳持续失败时，按缺陷清单格式记录问题，并运行：",
        "",
        "```text",
        f"python main.py --hotfix-project {contract.get('deliverable_root')} "
        "--defect-intake defects.md --auto-release",
        "```",
        "",
        "该流程会校验缺陷、生成热修任务、重新做集成回归/发布/打包，"
        "并输出 `docs/defect_report.md`。",
        "",
        "## 限制（如实说明）",
        "",
        str(contract.get("limitations") or ""),
        "",
    ]
    return "\n".join(lines)


def write_monitoring_contract(
    deliverable_root: str | Path,
    *,
    project: str,
    release: dict[str, Any] | None = None,
    created_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Write the monitoring contract and guide into the deliverable."""
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError(f"deliverable root does not exist: {root}")
    contract = build_monitoring_contract(
        project=project,
        deliverable_root=str(root),
        release=release,
        created_at=created_at,
    )
    directory = root / MONITORING_DIR
    directory.mkdir(parents=True, exist_ok=True)
    contract_path = directory / HEALTH_CONTRACT_FILENAME
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    doc_path = root / MONITORING_DOC_FILENAME
    doc_path.write_text(render_monitoring_doc(contract), encoding="utf-8")
    return {
        "status": "configured",
        "contract": str(contract_path),
        "doc": str(doc_path),
        "probes": [probe["id"] for probe in contract["probes"]],
        "release": (contract.get("release") or {}).get("version"),
    }


def _parse_manifest_checksums(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        match = _MANIFEST_ROW.match(line.strip())
        if match is not None:
            entries[match.group(1).strip()] = match.group(2).lower()
    return entries


def _check_release_anchor(root: Path) -> dict[str, Any]:
    try:
        released = load_release_log(root)
    except Exception as exc:
        return {"id": PROBE_RELEASE_ANCHOR, "status": "fail", "reason": f"{type(exc).__name__}: {exc}"}
    if not released:
        return {
            "id": PROBE_RELEASE_ANCHOR,
            "status": "unavailable",
            "reason": "交付物没有发布记录（release_log.json 缺失或为空）",
        }
    latest = released[-1]
    missing = [
        key for key in ("version", "tag", "commit")
        if not isinstance(latest.get(key), str) or not str(latest.get(key)).strip()
    ]
    if missing:
        return {
            "id": PROBE_RELEASE_ANCHOR,
            "status": "fail",
            "reason": "最新发布记录缺字段：" + ", ".join(missing),
        }
    return {
        "id": PROBE_RELEASE_ANCHOR,
        "status": "pass",
        "version": latest["version"],
        "tag": latest["tag"],
        "commit": latest["commit"],
    }


def _check_manifest_integrity(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return {
            "id": PROBE_MANIFEST_INTEGRITY,
            "status": "fail",
            "reason": f"{MANIFEST_FILENAME} 不存在",
        }
    try:
        checksums = _parse_manifest_checksums(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {"id": PROBE_MANIFEST_INTEGRITY, "status": "fail", "reason": str(exc)}
    if not checksums:
        return {
            "id": PROBE_MANIFEST_INTEGRITY,
            "status": "fail",
            "reason": "交付清单没有可校验的文件行",
        }
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, expected in checksums.items():
        target = root / relative
        if not target.is_file():
            missing.append(relative)
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            mismatched.append(relative)
    if missing or mismatched:
        return {
            "id": PROBE_MANIFEST_INTEGRITY,
            "status": "fail",
            "checked": len(checksums),
            "missing": missing,
            "mismatched": mismatched,
        }
    return {"id": PROBE_MANIFEST_INTEGRITY, "status": "pass", "checked": len(checksums)}


def _check_smoke_suite(
    root: Path, *, python: str | None, timeout: float, run_smoke: bool
) -> dict[str, Any]:
    if not run_smoke:
        return {
            "id": PROBE_SMOKE_SUITE,
            "status": "unavailable",
            "reason": "本次心跳跳过了回归套件",
        }
    kwargs: dict[str, Any] = {"timeout": timeout}
    if python is not None:
        kwargs["python"] = python
    result = run_smoke_verification(root, **kwargs)
    status = result.get("status")
    if status == "passed":
        return {"id": PROBE_SMOKE_SUITE, "status": "pass", "command": result.get("command")}
    if status == "skipped":
        return {
            "id": PROBE_SMOKE_SUITE,
            "status": "unavailable",
            "reason": result.get("reason") or "交付物没有测试文件",
        }
    return {
        "id": PROBE_SMOKE_SUITE,
        "status": "fail",
        "command": result.get("command"),
        "exit_code": result.get("exit_code"),
        "reason": result.get("reason") or "回归套件未通过",
    }


def _overall_status(probes: list[dict[str, Any]]) -> str:
    statuses = {probe.get("status") for probe in probes}
    if "fail" in statuses:
        return "failed"
    if "unavailable" in statuses:
        return "degraded"
    return "healthy"


def run_health_checks(
    deliverable_root: str | Path,
    *,
    python: str | None = None,
    timeout: float = DEFAULT_SMOKE_TIMEOUT,
    run_smoke: bool = True,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Run the heartbeat probes and write a deterministic status file.

    Never raises for a red deliverable: failures are evidenced in the status
    document (fail-closed reporting). Argument problems (missing directory,
    bad timeout) still raise.
    """
    root = Path(deliverable_root)
    if not root.is_dir():
        raise ValueError(f"deliverable root does not exist: {root}")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
    if python is not None and (not isinstance(python, str) or not python.strip()):
        raise ValueError("python must be a non-empty string or None")

    probes = [
        _check_release_anchor(root),
        _check_manifest_integrity(root),
        _check_smoke_suite(root, python=python, timeout=float(timeout), run_smoke=run_smoke),
    ]
    report = {
        "schema_version": 1,
        "deliverable_root": str(root),
        "generated_at": _timestamp(now),
        "status": _overall_status(probes),
        "probes": probes,
    }
    status_dir = root / MONITORING_DIR
    status_dir.mkdir(parents=True, exist_ok=True)
    status_path = status_dir / HEALTH_STATUS_FILENAME
    status_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report["status_file"] = str(status_path)
    return report


def render_health_report(report: dict[str, Any]) -> str:
    """Render a heartbeat result as a compact operator-facing table."""
    lines = [
        f"# 交付监控心跳（{report.get('status', '?').upper()}）",
        "",
        f"- 交付目录：{report.get('deliverable_root')}",
        f"- 生成时间：{report.get('generated_at')}",
        f"- 状态文件：{report.get('status_file')}",
        "",
        "| 探针 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    labels = {"pass": "通过", "fail": "失败", "unavailable": "不可用"}
    for probe in report.get("probes") or []:
        detail = probe.get("reason") or probe.get("command") or ""
        if probe.get("missing"):
            detail = f"缺失 {len(probe['missing'])} 个文件"
        elif probe.get("mismatched"):
            detail = f"校验不一致 {len(probe['mismatched'])} 个文件"
        lines.append(
            f"| {probe.get('id')} | {labels.get(probe.get('status'), probe.get('status'))} "
            f"| {detail} |"
        )
    lines.append("")
    return "\n".join(lines)
