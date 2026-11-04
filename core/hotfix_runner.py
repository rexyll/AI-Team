"""Standardized post-delivery hotfix flow: defects -> tasks -> repackage.

``run_hotfix`` wires the deterministic defect reflow into the existing project
pipeline: the hotfix plan replaces the planner output (no new analyst pass),
then the regular execution path performs integration regression, QA, release
(a patch version bump on the same deliverable git anchor), manifest and
packaging. Every outcome — fixed, pending, failed — is written into
``docs/defect_report.md`` rather than silently assumed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_router import AgentRouter
from runtime.defect_reflow import HotfixPreparation, prepare_hotfix, write_hotfix_artifacts
from security.workspace import WorkspaceSandbox, set_default_workspace_root

REQUIREMENTS_DOC = Path("docs") / "requirements.md"


def _final_status(delivery: dict[str, Any] | None) -> tuple[str, str | None]:
    """Classify the hotfix outcome from the real delivery record."""
    if not isinstance(delivery, dict):
        return "failed", "交付阶段未完成（doc_writer 未注册或文档生成失败）"
    integration = delivery.get("integration")
    if isinstance(integration, dict) and integration.get("status") == "failed":
        return "failed", "产品级集成回归未通过，已跳过打包"
    if delivery.get("package") is None:
        return "failed", "未生成交付包"
    release = delivery.get("release")
    if not isinstance(release, dict):
        return "failed", "发布阶段未执行"
    status = release.get("status")
    if status == "pending":
        return "pending", "发布待确认（使用 --auto-release 可跳过确认）"
    if status != "released":
        reason = release.get("reason") or release.get("error") or status
        return "failed", f"发布未完成：{reason}"
    return "fixed", None


def run_hotfix(
    agent_router: AgentRouter,
    deliverable_root: str | Path,
    intake_text: str,
    *,
    hotfix_version: str | None = None,
    auto_release: bool = False,
    knowledge_base: str | None = None,
    knowledge_query: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate defects, execute the hotfix plan and repackage the deliverable."""
    if not isinstance(agent_router, AgentRouter):
        raise TypeError("agent_router must be an AgentRouter")
    root = Path(deliverable_root)
    preparation: HotfixPreparation = prepare_hotfix(
        root, intake_text, hotfix_version=hotfix_version
    )
    # The change request and an in-progress report exist before execution, so a
    # crash mid-run still leaves an auditable trail.
    artifacts = write_hotfix_artifacts(preparation, status="prepared", now=now)

    parent = root.resolve().parent
    set_default_workspace_root(parent)
    sandbox = WorkspaceSandbox(parent)
    requirements = root / REQUIREMENTS_DOC
    analysis = (
        requirements.read_text(encoding="utf-8", errors="replace")
        if requirements.is_file()
        else ""
    )
    orchestrator = ProjectOrchestrator(
        agent_router=agent_router,
        deliverable_dir=root.name,
        sandbox=sandbox,
        release_requested=True,
        release_version=preparation.hotfix_version,
        auto_release=auto_release,
        knowledge_base=knowledge_base,
        knowledge_query=knowledge_query,
    )
    # No new analyst/planner pass: the hotfix plan is the authoritative task
    # graph, and the previous requirements document is the traceability basis.
    orchestrator.last_plan = preparation.plan
    orchestrator.last_requirement_analysis = analysis
    task_manager = orchestrator.build_task_manager(preparation.plan)
    result = orchestrator.execute(task_manager)
    delivery = orchestrator.last_delivery

    status, reason = _final_status(delivery)
    final = write_hotfix_artifacts(
        preparation, status=status, delivery=delivery, error=reason, now=now
    )
    release = delivery.get("release") if isinstance(delivery, dict) else None
    return {
        "status": status,
        "reason": reason,
        "version": release.get("version") if isinstance(release, dict) else None,
        "baseline_version": preparation.baseline_version,
        "target_version": preparation.hotfix_version,
        "defects": [defect.to_dict() for defect in preparation.defects],
        "plan": preparation.plan,
        "report": final["report"],
        "change_request": final["change_request"],
        "prepared_artifacts": artifacts,
        "delivery": delivery,
        "result": result,
        "task_manager": task_manager,
    }
