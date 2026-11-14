"""Deterministic deployment-readiness review for the release/operations role.

Before a delivery is handed to operations, the SRE role checks that the
artefacts operations will actually rely on exist and are internally
consistent: a deployment guide covering install/start/rollback, the
monitoring contract and its operating document, the standard handover
document set, and - when a release happened - the release notes for the
released version.

The verdict is deterministic (``READY`` / ``DEGRADED``) so it can be
asserted offline. The SRE agent adds narrative triage on top but cannot
lower a deterministic failure; results are reported, not silently turned
into success. External cloud deployment/APM integration remains an explicit
limitation of this runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MONITORING_CONTRACT = Path("monitoring") / "health_contract.json"
_MONITORING_DOC = Path("MONITORING.md")
_DEPLOYMENT_DOCS = (Path("docs") / "deployment.md", Path("docs") / "DEPLOYMENT.md")
_HANDOVER_DOCS = (
    Path("docs") / "requirements.md",
    Path("docs") / "design.md",
    Path("docs") / "test_report.md",
    Path("docs") / "user_manual.md",
)

_INSTALL_MARKERS = ("安装", "install", "pip install", "npm install")
_START_MARKERS = ("启动", "运行", "start", "run", "python main.py")
_ROLLBACK_MARKERS = ("回退", "回滚", "rollback")


def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "detail": detail,
    }


def _deployment_doc(root: Path) -> tuple[Path | None, str]:
    for candidate in _DEPLOYMENT_DOCS:
        path = root / candidate
        if path.is_file():
            return path, path.read_text(encoding="utf-8", errors="replace")
    return None, ""


def run_deployment_readiness(
    deliverable_root: str | Path,
    *,
    release: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate deployment readiness for one deliverable."""
    root = Path(deliverable_root)
    if not root.is_dir():
        return {
            "status": "skipped",
            "verdict": "SRE_SKIPPED",
            "reason": "deliverable root does not exist",
            "checks": [],
        }

    checks: list[dict[str, Any]] = []

    deployment_path, deployment_text = _deployment_doc(root)
    lowered = deployment_text.casefold()
    missing = []
    if deployment_path is None:
        missing = ["部署指引缺失"]
    else:
        if not any(marker.casefold() in lowered for marker in _INSTALL_MARKERS):
            missing.append("缺少依赖安装步骤")
        if not any(marker.casefold() in lowered for marker in _START_MARKERS):
            missing.append("缺少启动/运行命令")
        if not any(marker.casefold() in lowered for marker in _ROLLBACK_MARKERS):
            missing.append("缺少回退/回滚方式")
    checks.append(
        _check(
            "deployment_guide",
            deployment_path is not None and not missing,
            "部署指引完整" if deployment_path is not None and not missing
            else "；".join(missing),
        )
    )

    handover_missing = [str(path).replace("\\", "/") for path in _HANDOVER_DOCS if not (root / path).is_file()]
    checks.append(
        _check(
            "handover_documents",
            not handover_missing,
            "交付文档齐全" if not handover_missing else "缺失: " + ", ".join(handover_missing),
        )
    )

    contract_path = root / _MONITORING_CONTRACT
    contract_ok = False
    contract_detail = "监控契约缺失"
    if contract_path.is_file():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contract_detail = "监控契约不是合法 JSON"
        else:
            contract_ok = isinstance(contract, dict) and bool(contract.get("probes"))
            contract_detail = "监控契约可解析且包含探针" if contract_ok else "监控契约缺少探针"
    checks.append(_check("monitoring_contract", contract_ok, contract_detail))

    monitoring_doc = root / _MONITORING_DOC
    checks.append(
        _check(
            "monitoring_runbook",
            monitoring_doc.is_file(),
            "MONITORING.md 存在" if monitoring_doc.is_file() else "MONITORING.md 缺失",
        )
    )

    released_version = None
    if isinstance(release, dict) and release.get("status") == "released":
        released_version = release.get("version")
    if released_version:
        notes = root / "RELEASE_NOTES.md"
        notes_text = (
            notes.read_text(encoding="utf-8", errors="replace") if notes.is_file() else ""
        )
        checks.append(
            _check(
                "release_notes",
                str(released_version) in notes_text,
                f"RELEASE_NOTES.md 记录版本 {released_version}"
                if str(released_version) in notes_text
                else f"RELEASE_NOTES.md 未记录版本 {released_version}",
            )
        )
    else:
        checks.append(
            _check(
                "release_notes",
                True,
                "未发生发布，跳过发布说明检查",
            )
        )

    failed = [check["id"] for check in checks if check["status"] == "failed"]
    return {
        "status": "completed",
        "verdict": "SRE_READY" if not failed else "SRE_DEGRADED",
        "failed_checks": failed,
        "checks": checks,
        "limitation": (
            "本运行时未连接客户部署环境，部署就绪审查基于交付物内可验证的证据；"
            "真实云部署/APM 接入需客户运维在目标环境执行。"
        ),
    }


def render_sre_report(readiness: dict[str, Any], *, review: dict[str, Any] | None = None) -> str:
    """Render the human-readable deployment readiness report."""
    lines = [
        "# 部署就绪审查（SRE Readiness）",
        "",
        f"- 结论：**{readiness.get('verdict', 'SRE_SKIPPED')}**",
        "",
        "## 检查项",
        "",
        "| 检查项 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for check in readiness.get("checks") or []:
        lines.append(f"| {check['id']} | {check['status']} | {check['detail']} |")
    if not readiness.get("checks"):
        lines.append("| - | skipped | 无可审查的交付物根目录 |")

    if review:
        lines.extend(["", "## 运维工程师复核", ""])
        lines.append(f"- Agent 结论：{review.get('verdict', 'UNKNOWN')}")
        if review.get("summary"):
            lines.append(f"- 说明：{review['summary']}")

    limitation = readiness.get("limitation")
    if limitation:
        lines.extend(["", "## 边界说明", "", f"- {limitation}"])
    return "\n".join(lines).rstrip() + "\n"


def write_sre_report(
    deliverable_root: str | Path,
    readiness: dict[str, Any],
    *,
    review: dict[str, Any] | None = None,
) -> Path:
    """Write ``docs/sre_readiness.md`` and return its path."""
    root = Path(deliverable_root)
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "sre_readiness.md"
    path.write_text(render_sre_report(readiness, review=review), encoding="utf-8")
    return path


def sre_evidence_digest(readiness: dict[str, Any]) -> str:
    """Compact JSON digest handed to the SRE agent for triage."""
    return json.dumps(
        {
            "deterministic_verdict": readiness.get("verdict"),
            "failed_checks": readiness.get("failed_checks", []),
            "checks": readiness.get("checks", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
