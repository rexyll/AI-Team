from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agents.analyst import run_quality_checked_analysis
from runtime.clarification_session import ClarificationSession, prompt_for_answers
from core.hotfix_runner import run_hotfix
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_factory import create_agent_router
from runtime.github_scm_config import create_github_scm_runtime
from runtime.scm_lifecycle import SCMLifecycleConfig, SCMLifecycleCoordinator
from runtime.scm_provider import scm_merge_approval_target, scm_pull_request_approval_target
from runtime.dashboard_cli import write_dashboard
from runtime.deployment_host import DeploymentHostRuntime
from runtime.knowledge_base import (
    DEFAULT_KNOWLEDGE_LIMIT,
    KnowledgeBase,
    build_knowledge_prompt,
    extract_deliverable_knowledge,
    render_knowledge_list,
)
from runtime.model_usage import ModelUsageLedger
from runtime.monitoring import render_health_report, run_health_checks
from runtime.plan_constraints import extract_required_paths
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.release_plan import (
    collect_release_history,
    load_release_plan_file,
    plan_summary,
    render_release_history,
    write_release_plan,
)
from security.workspace import PROJECT_ROOT, set_default_workspace_root


CLI_OUTPUT_MODES = ("text", "json")
DEFAULT_KNOWLEDGE_BASE = "knowledge"


def _read_host_confirmation(prompt: str, *, display_stream: Any) -> str:
    """Require terminal input and a visible preview/confirmation destination."""
    input_is_tty = callable(getattr(sys.stdin, "isatty", None)) and sys.stdin.isatty()
    preview_is_tty = (
        callable(getattr(display_stream, "isatty", None)) and display_stream.isatty()
    )
    prompt_is_tty = callable(getattr(sys.stderr, "isatty", None)) and sys.stderr.isatty()
    if not (input_is_tty and preview_is_tty and prompt_is_tty):
        raise RuntimeError(
            "SCM write requires an interactive terminal and a visible terminal preview; "
            "no remote write was performed"
        )
    print(prompt, file=sys.stderr, flush=True)
    return input().strip()


def _ensure_log_safe_streams() -> None:
    """Make console logging resilient to unencodable characters."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Team - AI Software Development Team")
    parser.add_argument("requirement", nargs="?", default=None, help="Project requirement to execute. Optional with --resume-session.")
    parser.add_argument("--projects-base", default=None, help=f"Base directory for project sandboxes (default: {PROJECT_ROOT}).")
    parser.add_argument("--dashboard", metavar="PATH", default=None, help="Write a self-contained operational dashboard HTML file after execution.")
    parser.add_argument(
        "--output",
        choices=CLI_OUTPUT_MODES,
        default="text",
        help="Output format: text for human-readable output (default), json for machine-readable result output.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive clarification session: analyze the requirement, prompt for answers to the open questions, save the session, and continue into full delivery when clarification completes.",
    )
    parser.add_argument(
        "--session-path",
        metavar="PATH",
        default="clarification_session.json",
        help="Where the interactive clarification session is stored (default: clarification_session.json).",
    )
    parser.add_argument(
        "--resume-session",
        metavar="PATH",
        default=None,
        help="Resume a saved clarification session: prompt for remaining answers and continue into full delivery.",
    )
    parser.add_argument(
        "--strict-acceptance",
        action="store_true",
        help="Exit with a non-zero code when the deterministic acceptance verdict is FAILED.",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Run only the requirement analysis: write the structured draft spec (with open questions) to --analysis-output and exit, without starting a full delivery.",
    )
    parser.add_argument(
        "--analysis-output",
        metavar="PATH",
        default="requirement_analysis.md",
        help="Where --analyze-only writes the draft specification (default: requirement_analysis.md).",
    )
    parser.add_argument(
        "--clarifications",
        metavar="PATH",
        default=None,
        help="Path to a UTF-8 text file with customer answers to the analyst's open questions. Answers are treated as authoritative and integrated into the requirement specification.",
    )
    parser.add_argument(
        "--change-request",
        metavar="PATH",
        default=None,
        help="Path to a UTF-8 text file with the customer's change request. The analyst accepts it as an authoritative revision (CHG-xxx amendments) and re-plans the delivery around the amended specification.",
    )
    parser.add_argument(
        "--revise-project",
        metavar="PATH",
        default=None,
        help="Incrementally revise an existing persisted project snapshot (.json) after a change request: re-analyze and re-plan, then execute only the tasks affected by the change while unaffected completed tasks keep their evidence. Requires the original requirement and --change-request.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Run the release phase after a successful delivery: resolve the version, write release notes, anchor the deliverable in its own git repository (init/commit/tag) and record the release log. The release asks for confirmation unless --auto-release is given.",
    )
    parser.add_argument(
        "--release-version",
        metavar="VERSION",
        default=None,
        help="Explicit release version (MAJOR.MINOR.PATCH semver). Defaults to an automatic patch bump of the last recorded release.",
    )
    parser.add_argument(
        "--auto-release",
        action="store_true",
        help="Skip the release confirmation prompt (implies --release).",
    )
    parser.add_argument(
        "--milestone",
        metavar="NAME",
        default=None,
        help="Milestone label for a single delivery; recorded in RELEASE_NOTES.md and release_log.json.",
    )
    parser.add_argument(
        "--requirements-file",
        metavar="PATH",
        default=None,
        help="Run a milestone release plan: a UTF-8 Markdown file with '## 里程碑 ...' sections and '### 需求 ...' entries delivered sequentially, one version per delivery, plus a shared plan document.",
    )
    parser.add_argument(
        "--release-plan-output",
        metavar="PATH",
        default="release_plan.md",
        help="Where --requirements-file writes the shared plan/outcome document (default: release_plan.md).",
    )
    parser.add_argument(
        "--release-history",
        nargs="?",
        const="",
        metavar="PATH",
        default=None,
        help="Read-only: aggregate every release_log.json under PATH (default: projects base) and print the version history, then exit.",
    )
    parser.add_argument(
        "--knowledge-base",
        metavar="PATH",
        default=None,
        help="Cross-project knowledge base location (a .json file or a directory). When enabled, matching historical lessons are loaded into the analyst/doc-writer context and this delivery's lessons are extracted into the store.",
    )
    parser.add_argument(
        "--knowledge-query",
        metavar="TEXT",
        default=None,
        help="Keywords used to select which knowledge assets are loaded (default: load by kind/role priority).",
    )
    parser.add_argument(
        "--knowledge-list",
        nargs="?",
        const="",
        metavar="PATH",
        default=None,
        help="Read-only: list the knowledge assets stored at PATH (a .json file or a directory; default: knowledge/) and exit.",
    )
    parser.add_argument(
        "--knowledge-extract",
        metavar="PATH",
        default=None,
        help="Read-only: extract knowledge from an existing deliverable directory (release_log.json / docs/acceptance_report.md) and merge it into --knowledge-base, then exit.",
    )
    parser.add_argument(
        "--monitor-check",
        metavar="PATH",
        default=None,
        help="Run the post-delivery monitoring heartbeat on an existing deliverable directory and exit non-zero when the deliverable is unhealthy.",
    )
    parser.add_argument(
        "--deployment-history",
        metavar="PATH",
        default=None,
        help="Host-private SQLite deployment history. Also configured by AI_TEAM_DEPLOYMENT_HISTORY; when set, the CLI performs a read-only replacement-recovery inventory during startup.",
    )
    parser.add_argument(
        "--deployment-recovery-inventory",
        action="store_true",
        help="Standalone read-only report of unfinished deployment replacements from --deployment-history or AI_TEAM_DEPLOYMENT_HISTORY.",
    )
    parser.add_argument(
        "--deployment-recovery-inspect",
        action="store_true",
        help="Explicitly inspect recorded immutable Docker container IDs for unfinished replacements; does not inspect traffic routing or authorize recovery.",
    )
    parser.add_argument(
        "--deployment-reconciliation-readback",
        action="store_true",
        help="Read-only operator report: inspect both immutable runtimes and compare the durable Router registry with the live HAProxy selector and backend endpoints; performs no reconciliation action.",
    )
    parser.add_argument(
        "--scm-poll-pr",
        metavar="NUMBER",
        type=int,
        default=None,
        help="Read-only: poll a GitHub pull request's CI and review state using host environment credentials, then exit.",
    )
    parser.add_argument(
        "--scm-publish-pr",
        action="store_true",
        help="Publish a local branch and create/update its PR after two separate interactive confirmations.",
    )
    parser.add_argument(
        "--scm-merge-pr",
        metavar="NUMBER",
        type=int,
        default=None,
        help="Merge a PR only after fresh green CI and approved review evidence plus an interactive host confirmation.",
    )
    parser.add_argument(
        "--scm-merge-method",
        choices=("merge", "squash", "rebase"),
        default="squash",
        help="Merge method for --scm-merge-pr (default: squash).",
    )
    parser.add_argument("--scm-local-repository", metavar="PATH", default=None)
    parser.add_argument("--scm-head-branch", metavar="BRANCH", default=None)
    parser.add_argument("--scm-base-branch", metavar="BRANCH", default="main")
    parser.add_argument("--scm-pr-title", metavar="TITLE", default=None)
    parser.add_argument("--scm-pr-body-file", metavar="PATH", default=None)
    parser.add_argument(
        "--hotfix-project",
        metavar="PATH",
        default=None,
        help="Existing released deliverable directory to hotfix. Requires --defect-intake: the defects become hotfix tasks, then integration regression, a patch release and repackaging run on the same deliverable.",
    )
    parser.add_argument(
        "--defect-intake",
        metavar="PATH",
        default=None,
        help="UTF-8 Markdown defect list for --hotfix-project ('## 缺陷 DEF-001 标题' sections with 严重级别/描述/影响版本/复现步骤).",
    )
    parser.add_argument(
        "--hotfix-version",
        metavar="VERSION",
        default=None,
        help="Explicit hotfix version (MAJOR.MINOR.PATCH). Defaults to an automatic patch bump of the last release.",
    )
    return parser


def load_knowledge_prompt(
    path: str | None,
    *,
    roles: tuple[str, ...] | None = None,
    query: str | None = None,
) -> str:
    """Load role-relevant knowledge assets for a prompt, or '' when disabled."""
    return build_knowledge_prompt(path, roles=roles, query=query, limit=DEFAULT_KNOWLEDGE_LIMIT)


def print_knowledge_list(path: str, *, query: str | None = None, output: str = "text") -> int:
    """Print every stored knowledge asset (optionally keyword-filtered)."""
    store = KnowledgeBase(path)
    entries = store.search(query=query, limit=None)
    if output == "json":
        print(json.dumps(
            {
                "knowledge_base": str(store.path),
                "entries": [entry.to_dict() for entry in entries],
            },
            ensure_ascii=False,
            sort_keys=True,
        ))
    else:
        print(render_knowledge_list(entries))
        print(f"[Knowledge] 来源: {store.path}，共 {len(entries)} 条知识资产")
    return 0


def run_knowledge_extract(source: str, *, knowledge_base: str) -> dict[str, Any]:
    """Extract knowledge from an existing deliverable into the knowledge base."""
    entries = extract_deliverable_knowledge(source)
    store = KnowledgeBase(knowledge_base)
    counts = store.add(entries)
    return {"source": source, "knowledge_base": str(store.path), **counts}


def run_analysis_only(
    requirement: str,
    *,
    clarifications: str | None = None,
    change_request: str | None = None,
    output_path: str = "requirement_analysis.md",
    knowledge_base: str | None = None,
    knowledge_query: str | None = None,
):
    """Run only the requirement analysis and persist the draft specification.

    The file doubles as the clarification worksheet: the customer appends
    answers under the appended 客户答复 section and passes the file back via
    --clarifications for a full delivery run.
    """
    router = create_agent_router()
    analyst = router.get_agent("analyst")
    if analyst is None:
        raise ValueError("No analyst agent is registered")
    knowledge = load_knowledge_prompt(
        knowledge_base, roles=("analyst",), query=knowledge_query
    )
    result = run_quality_checked_analysis(
        analyst,
        requirement=requirement,
        clarifications=clarifications,
        change_request=change_request,
        knowledge=knowledge or None,
    )
    answers_template = (
        "（请逐条回答上方【待确认问题】；答复后运行："
        'python main.py "<原需求>" --clarifications ' + output_path + " 启动完整交付。）"
    )
    document = (
        result.message.rstrip()
        + "\n\n## 客户答复\n\n"
        + answers_template
        + "\n"
    )
    output = Path(output_path)
    output.write_text(document, encoding="utf-8")
    return result, output


def run_interactive_session(
    requirement: str,
    *,
    session_path: str = "clarification_session.json",
    resume_path: str | None = None,
    projects_base: str | None = None,
    strict_acceptance: bool = False,
):
    """Run the interactive clarification session and continue to delivery.

    Loads the saved session (or analyzes the requirement to start one),
    prompts for remaining open questions, persists the session, and — once
    clarification is complete — runs the full delivery with the answers as
    authoritative clarifications.
    """
    router = create_agent_router()
    analyst = router.get_agent("analyst")
    if analyst is None:
        raise ValueError("No analyst agent is registered")

    if resume_path:
        session = ClarificationSession.load(resume_path)
        if session.status == "delivered":
            print(f"[Session] 会话已完成交付: {resume_path}")
            return None, None, session
        requirement = session.requirement
        # Resume updates the session file in place.
        session_path = resume_path
    else:
        result = run_quality_checked_analysis(
            analyst, requirement=requirement, clarifications=None
        )
        session = ClarificationSession.create(requirement, result.message)

    if session.questions:
        answers = prompt_for_answers(session.questions, session.answers)
        session.answers = {str(k): v for k, v in answers.items()}
    session._refresh_status()
    session.save(session_path)
    print(f"[Session] 澄清会话已保存: {session_path} (status={session.status})")

    if not session.is_complete():
        print("[Session] 仍有未答复的问题；再次运行 --resume-session 可继续。")
        return None, None, session

    clarifications = session.answers_document()
    task_manager, result = run_project(
        requirement,
        projects_base=projects_base,
        clarifications=clarifications,
        strict_acceptance=strict_acceptance,
    )
    session.mark_delivered()
    session.save(session_path)
    return task_manager, result, session


def read_clarifications(path: str | None) -> str | None:
    """Load customer clarification answers from a UTF-8 text file."""
    return _read_utf8_document(path, empty_message="clarifications file cannot be empty")


def read_change_request(path: str | None) -> str | None:
    """Load the customer's change request from a UTF-8 text file."""
    return _read_utf8_document(path, empty_message="change request file cannot be empty")


def read_defect_intake(path: str | None) -> str | None:
    """Load the customer's defect list from a UTF-8 Markdown file."""
    return _read_utf8_document(path, empty_message="defect intake file cannot be empty")


def run_monitor_check(path: str, *, output: str = "text") -> int:
    """Run the post-delivery heartbeat; non-healthy deliverables exit non-zero."""
    report = run_health_checks(path)
    if output == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(render_health_report(report))
    return 0 if report["status"] == "healthy" else 1


def _read_utf8_document(path: str | None, *, empty_message: str) -> str | None:
    if path is None:
        return None
    document = Path(path).read_text(encoding="utf-8")
    if not document.strip():
        raise ValueError(empty_message)
    return document


class AcceptanceGateError(RuntimeError):
    """Raised with --strict-acceptance when the acceptance verdict is FAILED."""


def _prepare_workspace(requirement: str, projects_base: str | None) -> str | None:
    """Anchor the workspace for a delivery and return the mandated deliverable dir."""
    mandated_dirs = extract_required_paths(requirement)
    base = Path(projects_base) if projects_base else Path(PROJECT_ROOT)
    if mandated_dirs:
        # Local import: anchor helpers are only needed on the mandated path
        # (set_default_workspace_root itself stays a module-level import).
        from security.workspace import anchor_workspace_root, mandated_folded_prefix
        anchored = anchor_workspace_root(base, mandated_dirs[0])
        set_default_workspace_root(anchored, folded_prefix=mandated_folded_prefix(mandated_dirs[0]))
        # Pre-create the mandated deliverable directory: agents that explore
        # before writing must see it exist, or they burn their tool budget
        # re-checking a directory that is only created by their own writes.
        deliverable_path = anchored / mandated_dirs[0].replace("\\", "/").split("/")[-1]
        deliverable_path.mkdir(parents=True, exist_ok=True)
        print(f"[Workspace] 沙盒根已重定向到需求指定目录: {anchored}（产物将物理落位于 {mandated_dirs[0]}/ 之下）")
        return mandated_dirs[0].rsplit("/", 1)[-1]
    set_default_workspace_root(base)
    return None


def run_project(
    requirement: str,
    *,
    projects_base: str | None = None,
    clarifications: str | None = None,
    change_request: str | None = None,
    strict_acceptance: bool = False,
    release: bool = False,
    release_version: str | None = None,
    auto_release: bool = False,
    milestone: str | None = None,
    knowledge_base: str | None = None,
    knowledge_query: str | None = None,
    on_delivery: Callable[[dict | None], None] | None = None,
):
    if not isinstance(requirement, str):
        raise TypeError("requirement must be a string")
    if not requirement.strip():
        raise ValueError("requirement cannot be empty")

    deliverable_dir = _prepare_workspace(requirement, projects_base)
    router = create_agent_router(
        usage_ledger=(usage_ledger := ModelUsageLedger()),
        usage_project_id=(usage_project_id := f"run-{uuid4()}"),
    )
    scm_runtime = create_github_scm_runtime()
    project_orchestrator = ProjectOrchestrator(
        agent_router=router,
        scm_service=scm_runtime.service if scm_runtime else None,
        scm_repository=scm_runtime.repository if scm_runtime else None,
        scm_pull_request_number=scm_runtime.pull_request_number if scm_runtime else None,
        deliverable_dir=deliverable_dir,
        clarifications=clarifications,
        change_request=change_request,
        release_requested=release or auto_release,
        release_version=release_version,
        auto_release=auto_release,
        milestone=milestone,
        usage_ledger=usage_ledger,
        usage_project_id=usage_project_id,
        knowledge_base=knowledge_base,
        knowledge_query=knowledge_query,
    )
    plan = project_orchestrator.create_plan(requirement)
    task_manager = project_orchestrator.build_task_manager(plan)
    result = project_orchestrator.execute(task_manager)
    if on_delivery is not None:
        on_delivery(getattr(project_orchestrator, "last_delivery", None))
    if strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
        report = (getattr(project_orchestrator, "last_acceptance", None) or {}).get("report")
        raise AcceptanceGateError(
            f"验收结论为 FAILED；验收报告: {report or '未知'}"
        )
    return task_manager, result


def run_project_revision(
    requirement: str,
    *,
    project_path: str,
    change_request: str,
    projects_base: str | None = None,
    strict_acceptance: bool = False,
    release: bool = False,
    release_version: str | None = None,
    auto_release: bool = False,
    knowledge_base: str | None = None,
    knowledge_query: str | None = None,
):
    """Incrementally revise a persisted project after a change request.

    The requirement is re-analyzed with the change request and re-planned;
    only the tasks affected by the revision are executed, unaffected completed
    tasks keep their evidence, and the revised snapshot is persisted in place.
    """
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("requirement cannot be empty")
    if not isinstance(change_request, str) or not change_request.strip():
        raise ValueError("a non-empty change request is required to revise a persisted project")
    snapshot_path = Path(project_path)
    if not snapshot_path.is_file():
        raise ValueError(f"persisted project snapshot not found: {project_path}")

    deliverable_dir = _prepare_workspace(requirement, projects_base)
    router = create_agent_router(
        usage_ledger=(usage_ledger := ModelUsageLedger()),
        usage_project_id=(usage_project_id := f"revise-{uuid4()}"),
    )
    scm_runtime = create_github_scm_runtime()
    project_orchestrator = ProjectOrchestrator(
        agent_router=router,
        scm_service=scm_runtime.service if scm_runtime else None,
        scm_repository=scm_runtime.repository if scm_runtime else None,
        scm_pull_request_number=scm_runtime.pull_request_number if scm_runtime else None,
        deliverable_dir=deliverable_dir,
        change_request=change_request,
        release_requested=release or auto_release,
        release_version=release_version,
        auto_release=auto_release,
        usage_ledger=usage_ledger,
        usage_project_id=usage_project_id,
        knowledge_base=knowledge_base,
        knowledge_query=knowledge_query,
    )
    adapter = ProjectPersistenceAdapter(snapshot_path.parent)
    result, revision = project_orchestrator.revise_persisted(
        snapshot_path.stem, adapter, requirement
    )
    if strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
        report = (getattr(project_orchestrator, "last_acceptance", None) or {}).get("report")
        raise AcceptanceGateError(
            f"验收结论为 FAILED；验收报告: {report or '未知'}"
        )
    return project_orchestrator.last_task_manager, result, revision


def run_release_plan(
    plan,
    *,
    projects_base: str | None = None,
    release: bool = False,
    auto_release: bool = False,
    strict_acceptance: bool = False,
    plan_output: str = "release_plan.md",
    knowledge_base: str | None = None,
    knowledge_query: str | None = None,
    runner: Callable[..., tuple] | None = None,
    now: Any = None,
    verbose: bool = True,
):
    """Deliver a milestone plan's requirements sequentially, then write the plan.

    Every requirement is a full delivery on its own (its own analysis, task
    graph, tests, integration, packaging and version). A failure stops the
    batch - remaining requirements are recorded as ``skipped`` and the shared
    plan document is still written so the partial result is auditable.
    Returns ``(outcomes, plan_path)``.
    """
    if not callable(runner) and runner is not None:
        raise TypeError("runner must be callable or None")
    run_one = runner or run_project
    outcomes: list[dict[str, Any]] = []
    total = len(plan.entries)

    for entry in plan.entries:
        if verbose:
            print(f"[Plan] {entry.index}/{total} 里程碑 {entry.milestone} · {entry.title}")
        delivery: dict[str, Any] | None = None

        def observe(payload: dict[str, Any] | None) -> None:
            nonlocal delivery
            delivery = payload

        status = "completed"
        acceptance_verdict = None
        error = None
        run_kwargs: dict[str, Any] = {
            "projects_base": projects_base,
            "release": release or auto_release,
            "release_version": entry.version,
            "auto_release": auto_release,
            "strict_acceptance": strict_acceptance,
            "milestone": entry.milestone,
            "on_delivery": observe,
        }
        # Only pass knowledge options when enabled so custom runners keep the
        # documented minimal call signature.
        if knowledge_base is not None:
            run_kwargs["knowledge_base"] = knowledge_base
        if knowledge_query is not None:
            run_kwargs["knowledge_query"] = knowledge_query
        try:
            _, result = run_one(entry.requirement, **run_kwargs)
            acceptance_verdict = getattr(result, "acceptance_verdict", None)
            if not getattr(result, "success", False):
                status = "failed"
                error = f"delivery did not succeed (status={getattr(result, 'status', 'unknown')})"
        except Exception as exc:
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
        outcomes.append(
            {
                "index": entry.index,
                "milestone": entry.milestone,
                "title": entry.title,
                "status": status,
                "acceptance_verdict": acceptance_verdict,
                "release": (delivery or {}).get("release"),
                "deliverable_root": (delivery or {}).get("deliverable_root"),
                "error": error,
            }
        )
        if status == "failed":
            if verbose:
                print(f"[Plan] 需求 {entry.index} 失败，停止后续交付：{error}")
            break

    for entry in plan.entries[len(outcomes):]:
        outcomes.append(
            {
                "index": entry.index,
                "milestone": entry.milestone,
                "title": entry.title,
                "status": "skipped",
                "acceptance_verdict": None,
                "release": None,
                "deliverable_root": None,
                "error": "previous requirement failed",
            }
        )
    path = write_release_plan(plan, outcomes, plan_output, now=now)
    if verbose:
        print(f"[Plan] 共享发布计划已写入: {path}")
    return outcomes, path


def print_release_history(root: str, *, output: str = "text") -> int:
    """Print the aggregated release history for a deliverable base directory."""
    records = collect_release_history(root)
    if output == "json":
        print(json.dumps({"root": root, "releases": records}, ensure_ascii=False, sort_keys=True))
    else:
        print(render_release_history(records))
        print(f"[Release-History] 来源目录: {root}，共 {len(records)} 条发布记录")
    return 0


def _json_result(task_manager, result) -> str:
    """Serialize the stable CLI result contract without exposing raw runtime objects."""
    return json.dumps(
        {
            "result": result.to_dict() if hasattr(result, "to_dict") else {
                "success": result.success,
                "status": result.status,
                "total_tasks": result.total_tasks,
                "completed_tasks": result.completed_tasks,
            },
            "tasks": [
                {
                    "id": task.id,
                    "status": task.status,
                    "role": task.role,
                    "title": task.title,
                    "error": task.error,
                }
                for task in task_manager.get_all_tasks()
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main() -> int:
    _ensure_log_safe_streams()
    parser = build_parser()
    args = parser.parse_args()
    if args.requirement is None and not (
        args.interactive
        or args.resume_session
        or args.requirements_file
        or args.release_history is not None
        or args.knowledge_list is not None
        or args.knowledge_extract is not None
        or args.monitor_check is not None
        or args.hotfix_project is not None
        or args.scm_poll_pr is not None
        or args.scm_publish_pr
        or args.scm_merge_pr is not None
        or args.deployment_recovery_inventory
        or args.deployment_recovery_inspect
        or args.deployment_reconciliation_readback
    ):
        parser.error("the following arguments are required: requirement")

    deployment_history_path = (
        args.deployment_history or os.environ.get("AI_TEAM_DEPLOYMENT_HISTORY")
    )

    recovery_modes = (
        args.deployment_recovery_inventory,
        args.deployment_recovery_inspect,
        args.deployment_reconciliation_readback,
    )
    if sum(bool(item) for item in recovery_modes) > 1:
        parser.error("deployment recovery and reconciliation read-back modes are mutually exclusive")

    if any(recovery_modes):
        if any((
            args.requirement is not None,
            args.requirements_file is not None,
            args.interactive,
            args.resume_session is not None,
            args.analyze_only,
            args.clarifications is not None,
            args.change_request is not None,
            args.revise_project is not None,
            args.release,
            args.release_version is not None,
            args.auto_release,
            args.milestone is not None,
            args.release_history is not None,
            args.knowledge_base is not None,
            args.knowledge_query is not None,
            args.knowledge_list is not None,
            args.knowledge_extract is not None,
            args.monitor_check is not None,
            args.dashboard is not None,
            args.scm_poll_pr is not None,
            args.scm_publish_pr,
            args.scm_merge_pr is not None,
            args.hotfix_project is not None,
            args.defect_intake is not None,
        )):
            parser.error("--deployment-recovery-* and --deployment-reconciliation-readback are standalone")
        if not deployment_history_path:
            parser.error(
                "--deployment-recovery-* requires --deployment-history "
                "or AI_TEAM_DEPLOYMENT_HISTORY"
            )
        try:
            host_runtime = DeploymentHostRuntime(
                deployment_history_path,
                create_if_missing=False,
            )
            if args.deployment_reconciliation_readback:
                report = host_runtime.inspect_manual_reconciliation_readback()
            elif args.deployment_recovery_inspect:
                report = host_runtime.inspect_recovery()
            else:
                report = host_runtime.start().to_dict()
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        elif args.deployment_reconciliation_readback:
            print(
                f"[Deployment-Reconciliation-Readback] provider={report['provider']} "
                f"unfinished={report['unfinished_replacements']} "
                "automatic_action=none recovery=disabled"
            )
            for item in report["readbacks"]:
                previous = item["previous_runtime"]
                candidate = item["candidate_runtime"]
                route = item["route_readback"] or {}
                previous_summary = f"{previous['status']}/{previous['runtime_state']}/{previous['health_status']}"
                candidate_summary = f"{candidate['status']}/{candidate['runtime_state']}/{candidate['health_status']}"
                print(
                    f"  {item['operation_id']}: phase={item['phase']} "
                    f"assessment={item['assessment']} previous={previous_summary} "
                    f"candidate={candidate_summary} route={route.get('status', 'not_available')} "
                    f"selector={route.get('live_active_slot') or 'unknown'} "
                    f"effective_runtime={route.get('effective_runtime_id') or 'unknown'} "
                    "automatic_action=none"
                )
                for backend in route.get("backend_readbacks", []):
                    print(
                        f"    backend={backend['backend']} slot={backend['slot']} "
                        f"endpoint={backend['observed_address']}:{backend['observed_port']} "
                        f"status={backend['status']} sessions={backend['current_sessions']}"
                    )
        elif args.deployment_recovery_inspect:
            print(
                f"[Deployment-Recovery-Inspect] provider={report['provider']} "
                f"unfinished={report['unfinished_replacements']} "
                "route_readback=not_available recovery=disabled"
            )
            for item in report["observations"]:
                previous = item["previous_runtime"]
                candidate = item["candidate_runtime"]
                previous_summary = (
                    f"{previous['status']}/{previous['runtime_state']}/{previous['health_status']}"
                    if previous else "not_recorded"
                )
                candidate_summary = (
                    f"{candidate['status']}/{candidate['runtime_state']}/{candidate['health_status']}"
                    if candidate else "not_recorded"
                )
                print(
                    f"  {item['operation_id']}: previous={previous_summary} "
                    f"candidate={candidate_summary} route=not_available recovery=disabled"
                )
        else:
            print(
                f"[Deployment-Recovery] provider={report['provider']} "
                f"history={report['history_path']} "
                f"unfinished={report['unfinished_replacements']}"
            )
            for item in report["inventory"]:
                print(
                    f"  {item['operation_id']}: phase={item['phase']} "
                    f"classification={item['classification']} "
                    f"active={item['active_deployment_id'] or 'none'}"
                )
        return 0

    # main.py is the documented CLI host entry point. When deployment history
    # is explicitly configured, every process startup performs a read-only
    # inventory before dispatching any operation. No Docker command, route
    # update, journal mutation, or reservation release occurs here.
    if deployment_history_path:
        try:
            startup = DeploymentHostRuntime(deployment_history_path).start()
        except Exception as exc:
            print(f"[Deployment-Host] startup inventory failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if startup.inventory:
            summaries = ", ".join(
                f"{item.operation_id}:{item.classification}"
                for item in startup.inventory
            )
            print(
                f"[Deployment-Host] {len(startup.inventory)} unfinished replacement(s) "
                f"remain reserved ({summaries}); use --deployment-recovery-inventory, --deployment-recovery-inspect, or --deployment-reconciliation-readback for read-only evidence.",
                file=sys.stderr,
            )

    if args.scm_merge_pr is not None:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.revise_project is not None
            or args.change_request
            or args.release
            or args.auto_release
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.monitor_check is not None
            or args.scm_poll_pr is not None
            or args.scm_publish_pr
            or args.release_history is not None
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
        ):
            parser.error("--scm-merge-pr is standalone and cannot be combined with another operation")
        try:
            scm_runtime = create_github_scm_runtime(
                pull_request_number=args.scm_merge_pr
            )
            if scm_runtime is None:
                raise RuntimeError("GitHub SCM is not configured")
            coordinator = SCMLifecycleCoordinator(
                scm_runtime.service,
                SCMLifecycleConfig(repository=scm_runtime.repository),
            )
            observation = coordinator.poll_pull_request(args.scm_merge_pr)
            if observation["status"] != "ready":
                if args.output == "json":
                    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
                else:
                    print(
                        f"[SCM] Merge blocked for PR #{args.scm_merge_pr}: "
                        f"{observation['status']} (CI={observation['ci_status']}, "
                        f"Review={observation['review_status']})"
                    )
                return 2
            preview = (
                f"Repository: {scm_runtime.repository}\n"
                f"PR: #{args.scm_merge_pr}\n"
                f"Head SHA: {observation['head_sha']}\n"
                f"Base branch: {observation['base_branch']}\n"
                f"CI: {observation['ci_status']} | Review: {observation['review_status']}\n"
                f"Merge method: {args.scm_merge_method}"
            )
            confirmation_stream = sys.stderr if args.output == "json" else sys.stdout
            print(preview, file=confirmation_stream)
            confirmation = _read_host_confirmation(
                "Type 'yes' to approve merging this exact PR head into the displayed base branch "
                f"using {args.scm_merge_method} after fresh preflight: ",
                display_stream=confirmation_stream,
            )
            if confirmation != "yes":
                print(
                    "[SCM] Merge cancelled; no merge request was sent.",
                    file=sys.stderr if args.output == "json" else sys.stdout,
                )
                return 3
            approval = scm_runtime.approval_authority.issue(
                operation="merge_pull_request",
                repository=scm_runtime.repository,
                target=scm_merge_approval_target(
                    args.scm_merge_pr,
                    head_sha=observation["head_sha"],
                    base_branch=observation["base_branch"],
                    merge_method=args.scm_merge_method,
                ),
                approved_by="human:interactive-cli",
            )
            outcome = scm_runtime.service.merge_pull_request(
                scm_runtime.repository,
                args.scm_merge_pr,
                approval=approval,
                merge_method=args.scm_merge_method,
            )
            result = {
                "status": "merged",
                "repository": scm_runtime.repository,
                "pull_request_number": args.scm_merge_pr,
                "head_sha": observation["head_sha"],
                "base_branch": observation["base_branch"],
                "merge_method": args.scm_merge_method,
                "result": outcome,
            }
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(f"[SCM] PR #{args.scm_merge_pr} merged using {args.scm_merge_method}.")
        return 0

    if args.scm_publish_pr:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.revise_project is not None
            or args.change_request
            or args.release
            or args.auto_release
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.monitor_check is not None
            or args.scm_poll_pr is not None
            or args.scm_merge_pr is not None
            or args.release_history is not None
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
        ):
            parser.error("--scm-publish-pr is standalone and cannot be combined with another operation")
        missing = [
            name for name, value in (
                ("--scm-local-repository", args.scm_local_repository),
                ("--scm-head-branch", args.scm_head_branch),
                ("--scm-pr-title", args.scm_pr_title),
                ("--scm-pr-body-file", args.scm_pr_body_file),
            ) if not value
        ]
        if missing:
            parser.error("--scm-publish-pr requires " + ", ".join(missing))
        try:
            scm_runtime = create_github_scm_runtime(require_pull_request=False)
            if scm_runtime is None:
                raise RuntimeError("GitHub SCM is not configured")
            body = Path(args.scm_pr_body_file).read_text(encoding="utf-8")
            if not body.strip():
                raise ValueError("PR body file must not be empty")
            coordinator = SCMLifecycleCoordinator(
                scm_runtime.service,
                SCMLifecycleConfig(
                    repository=scm_runtime.repository,
                    base_branch=args.scm_base_branch,
                ),
            )
            head_sha = scm_runtime.service.get_local_head_sha(
                args.scm_local_repository
            )
            pr_approval_target = scm_pull_request_approval_target(
                head=args.scm_head_branch,
                base=args.scm_base_branch,
                title=args.scm_pr_title,
                body=body,
                expected_head_sha=head_sha,
            )
            pr_payload_sha256 = pr_approval_target.rsplit("sha256=", 1)[1]
            preview = (
                f"Repository: {scm_runtime.repository}\n"
                f"Local repository: {args.scm_local_repository}\n"
                f"Push: {args.scm_head_branch} @ {head_sha}\n"
                f"PR: {args.scm_head_branch} -> {args.scm_base_branch}\n"
                f"PR source SHA: {head_sha}\n"
                f"Title: {args.scm_pr_title}\n"
                f"PR body (JSON-escaped): {json.dumps(body, ensure_ascii=True)}\n"
                f"PR approval SHA-256 (source SHA + title + body): {pr_payload_sha256}"
            )
            confirmation_stream = sys.stderr if args.output == "json" else sys.stdout
            print(preview, file=confirmation_stream)
            push_confirmation = _read_host_confirmation(
                "Type 'yes' to approve pushing this exact HEAD to the target branch: ",
                display_stream=confirmation_stream,
            )
            if push_confirmation != "yes":
                print("[SCM] Push cancelled; no remote write was performed.", file=sys.stderr if args.output == "json" else sys.stdout)
                return 3
            pr_confirmation = _read_host_confirmation(
                "Type 'yes' separately to approve creating/updating the displayed pull request payload: ",
                display_stream=confirmation_stream,
            )
            if pr_confirmation != "yes":
                print("[SCM] PR creation cancelled; no remote write was performed.", file=sys.stderr if args.output == "json" else sys.stdout)
                return 3
            authority = scm_runtime.approval_authority
            push_approval = authority.issue(
                operation="push_branch",
                repository=scm_runtime.repository,
                target=f"{args.scm_head_branch}:{head_sha}",
                approved_by="human:interactive-cli",
            )
            pr_approval = authority.issue(
                operation="create_or_update_pull_request",
                repository=scm_runtime.repository,
                target=pr_approval_target,
                approved_by="human:interactive-cli",
            )
            outcome = coordinator.publish_and_open_pull_request(
                local_repository=args.scm_local_repository,
                head_branch=args.scm_head_branch,
                title=args.scm_pr_title,
                body=body,
                push_approval=push_approval,
                pull_request_approval=pr_approval,
            )
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
        else:
            pull_request = outcome["pull_request"]
            print(
                f"[SCM] Published {outcome['repository']}:{outcome['head_branch']} "
                f"-> PR #{pull_request['number']} ({pull_request['status']})"
            )
        return 0

    if args.scm_poll_pr is not None:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.revise_project is not None
            or args.change_request
            or args.release
            or args.auto_release
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.monitor_check is not None
            or args.scm_publish_pr
            or args.scm_merge_pr is not None
            or args.release_history is not None
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
        ):
            parser.error("--scm-poll-pr is read-only and cannot be combined with a delivery or other operation")
        try:
            scm_runtime = create_github_scm_runtime(
                pull_request_number=args.scm_poll_pr
            )
            if scm_runtime is None:
                raise RuntimeError("GitHub SCM is not configured")
            coordinator = SCMLifecycleCoordinator(
                scm_runtime.service,
                SCMLifecycleConfig(repository=scm_runtime.repository),
            )
            observation = coordinator.poll_pull_request(scm_runtime.pull_request_number)
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"[SCM] PR #{observation['pull_request_number']} "
                f"{observation['status']} | head={observation['head_sha']} "
                f"| CI={observation['ci_status']} | Review={observation['review_status']} "
                f"| attempts={observation['attempt']}/{observation['max_attempts']}"
            )
        return 0 if observation["status"] == "ready" else 2

    if args.monitor_check is not None:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.revise_project is not None
        ):
            parser.error("--monitor-check is read-only and cannot be combined with a delivery request")
        try:
            return run_monitor_check(args.monitor_check, output=args.output)
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.release_history is not None:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
            or args.monitor_check is not None
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.revise_project is not None
        ):
            parser.error("--release-history is read-only and cannot be combined with a delivery request")
        root = args.release_history or args.projects_base or str(PROJECT_ROOT)
        try:
            return print_release_history(root, output=args.output)
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.knowledge_list is not None:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.knowledge_extract is not None
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.revise_project is not None
        ):
            parser.error("--knowledge-list is read-only and cannot be combined with a delivery request")
        store_path = args.knowledge_list or args.knowledge_base or DEFAULT_KNOWLEDGE_BASE
        try:
            return print_knowledge_list(
                store_path, query=args.knowledge_query, output=args.output
            )
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.knowledge_extract is not None:
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.revise_project is not None
        ):
            parser.error("--knowledge-extract cannot be combined with a delivery request")
        store_path = args.knowledge_base or DEFAULT_KNOWLEDGE_BASE
        try:
            outcome = run_knowledge_extract(args.knowledge_extract, knowledge_base=store_path)
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"[Knowledge] 从 {outcome['source']} 提取知识资产："
                f"新增 {outcome['added']}，去重 {outcome['duplicates']}，累计 {outcome['total']}"
                f"（存储: {outcome['knowledge_base']}）"
            )
        return 0

    if args.hotfix_project is not None or args.defect_intake is not None:
        if args.hotfix_project is None:
            parser.error("--defect-intake requires --hotfix-project")
        if args.defect_intake is None:
            parser.error("--hotfix-project requires --defect-intake")
        if (
            args.requirement is not None
            or args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
            or args.clarifications
            or args.change_request
            or args.milestone
            or args.release_version
            or args.strict_acceptance
            or args.revise_project is not None
        ):
            parser.error(
                "--hotfix-project is a standalone defect-reflow run and cannot be "
                "combined with a delivery request or --release-version"
            )
        try:
            intake = read_defect_intake(args.defect_intake)
            router = create_agent_router(
                usage_ledger=ModelUsageLedger(),
                usage_project_id=f"hotfix-{uuid4()}",
            )
            outcome = run_hotfix(
                router,
                args.hotfix_project,
                intake,
                hotfix_version=args.hotfix_version,
                auto_release=args.auto_release,
                knowledge_base=args.knowledge_base,
                knowledge_query=args.knowledge_query,
            )
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        delivery = outcome.get("delivery") if isinstance(outcome.get("delivery"), dict) else {}
        package = delivery.get("package") if isinstance(delivery.get("package"), dict) else {}
        if args.output == "json":
            print(json.dumps(
                {
                    "status": outcome["status"],
                    "reason": outcome["reason"],
                    "version": outcome["version"],
                    "baseline_version": outcome["baseline_version"],
                    "target_version": outcome["target_version"],
                    "defects": [defect["id"] for defect in outcome["defects"]],
                    "report": outcome["report"],
                    "change_request": outcome["change_request"],
                    "package": package.get("archive"),
                    "tasks": [
                        {"id": task.id, "status": task.status, "role": task.role}
                        for task in outcome["task_manager"].get_all_tasks()
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ))
        else:
            reason = f"（{outcome['reason']}）" if outcome["reason"] else ""
            print(
                f"[Hotfix] 缺陷回流 v{outcome['baseline_version']} -> "
                f"v{outcome['target_version']}：{len(outcome['defects'])} 个缺陷"
            )
            print(f"[Hotfix] 状态: {outcome['status']}{reason}")
            print(f"[Hotfix] 缺陷报告: {outcome['report']}")
            print(f"[Hotfix] 变更请求: {outcome['change_request']}")
            if package.get("archive"):
                print(f"[Hotfix] 交付包: {package['archive']}")
        return 0 if outcome["status"] == "fixed" else 1

    if args.revise_project is not None:
        if args.requirement is None:
            parser.error("--revise-project requires the original requirement as a positional argument")
        if not args.change_request:
            parser.error("--revise-project requires --change-request")
        if (
            args.requirements_file
            or args.interactive
            or args.resume_session
            or args.analyze_only
            or args.hotfix_project is not None
            or args.defect_intake is not None
            or args.monitor_check is not None
            or args.release_history is not None
            or args.knowledge_list is not None
            or args.knowledge_extract is not None
        ):
            parser.error(
                "--revise-project is a standalone incremental revision and cannot be "
                "combined with another delivery mode"
            )
        try:
            task_manager, result, revision = run_project_revision(
                args.requirement,
                project_path=args.revise_project,
                change_request=read_change_request(args.change_request),
                projects_base=args.projects_base,
                strict_acceptance=args.strict_acceptance,
                release=args.release,
                release_version=args.release_version,
                auto_release=args.auto_release,
                knowledge_base=args.knowledge_base,
                knowledge_query=args.knowledge_query,
            )
        except AcceptanceGateError as exc:
            print(f"[ACCEPTANCE-GATE] {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            payload = json.loads(_json_result(task_manager, result))
            payload["revision"] = revision
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            if args.strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
                print("[ACCEPTANCE-GATE] 验收结论为 FAILED：按 --strict-acceptance 以非零码退出。", file=sys.stderr)
                return 1
            return 0
        print(
            f"[Revision] 模式 {revision['mode']}：复用 {len(revision['reused'])} 个已完成任务，"
            f"重执行 {len(revision['affected'])} 个，新增 {len(revision['added'])} 个，"
            f"移除 {len(revision['removed'])} 个（快照: {args.revise_project}）"
        )

    if args.requirements_file:
        if args.requirement is not None:
            parser.error("--requirements-file and a positional requirement are mutually exclusive")
        if args.interactive or args.resume_session or args.analyze_only:
            parser.error("--requirements-file cannot be combined with --interactive/--resume-session/--analyze-only")
        if args.release_version:
            parser.error("--release-version cannot be combined with --requirements-file; pin versions per requirement with [vX.Y.Z]")
        if args.milestone:
            parser.error("--milestone only applies to a single requirement; use '## 里程碑' sections in the plan file")
        if args.clarifications or args.change_request:
            parser.error("--clarifications/--change-request cannot be combined with --requirements-file")
        try:
            plan = load_release_plan_file(args.requirements_file)
            outcomes, plan_path = run_release_plan(
                plan,
                projects_base=args.projects_base,
                release=args.release or args.auto_release,
                auto_release=args.auto_release,
                strict_acceptance=args.strict_acceptance,
                plan_output=args.release_plan_output,
                knowledge_base=args.knowledge_base,
                knowledge_query=args.knowledge_query,
                verbose=args.output != "json",
            )
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(
                {
                    "plan": str(plan_path),
                    "plan_meta": plan_summary(plan),
                    "outcomes": outcomes,
                },
                ensure_ascii=False,
                sort_keys=True,
            ))
        else:
            completed = sum(1 for outcome in outcomes if outcome["status"] == "completed")
            print()
            print("PLAN RESULT")
            print(f"completed={completed}/{len(outcomes)} plan={plan_path}")
        return 0 if all(outcome["status"] == "completed" for outcome in outcomes) else 1

    if args.interactive or args.resume_session:
        task_manager, result, session = run_interactive_session(
            args.requirement or "",
            session_path=args.session_path,
            resume_path=args.resume_session,
            projects_base=args.projects_base,
            strict_acceptance=args.strict_acceptance,
        )
        if task_manager is None:
            return 0
        if args.output == "json":
            print(_json_result(task_manager, result))
        return 0

    if args.analyze_only:
        result, output = run_analysis_only(
            args.requirement,
            clarifications=read_clarifications(args.clarifications),
            change_request=read_change_request(args.change_request),
            output_path=args.analysis_output,
            knowledge_base=args.knowledge_base,
            knowledge_query=args.knowledge_query,
        )
        quality = result.data.get("quality") or {}
        print(f"[Analysis] 需求规格草案已写入: {output} (attempts={result.data.get('attempts')}, quality_ok={quality.get('ok')})")
        print("[Analysis] 请在文末『客户答复』章节逐条回答【待确认问题】，再使用 --clarifications 启动完整交付。")
        return 0

    try:
        clarifications = read_clarifications(args.clarifications)
        change_request = read_change_request(args.change_request)
        task_manager, result = run_project(
            args.requirement,
            projects_base=args.projects_base,
            clarifications=clarifications,
            change_request=change_request,
            strict_acceptance=args.strict_acceptance,
            release=args.release,
            release_version=args.release_version,
            auto_release=args.auto_release,
            milestone=args.milestone,
            knowledge_base=args.knowledge_base,
            knowledge_query=args.knowledge_query,
        )
        if args.dashboard:
            project_id = None
            write_dashboard(task_manager.get_all_tasks(), args.dashboard, project_id=project_id)
            if args.output == "text":
                print(f"[Dashboard] 已生成: {Path(args.dashboard)}")
    except AcceptanceGateError as exc:
        print(f"[ACCEPTANCE-GATE] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(_json_result(task_manager, result))
        if args.strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
            print("[ACCEPTANCE-GATE] 验收结论为 FAILED：按 --strict-acceptance 以非零码退出。", file=sys.stderr)
            return 1
        return 0

    print()
    print("=" * 60)
    print("PROJECT RESULT")
    print("=" * 60)
    print(f"success={result.success} status={result.status} completed={result.completed_tasks}/{result.total_tasks}")
    print()
    print("=" * 60)
    print("FINAL TASK STATUS")
    print("=" * 60)
    for task in task_manager.get_all_tasks():
        print(f"{task.id:<12}{task.status:<14}{task.role:<12}{task.title}")
        if task.error:
            print(f"    ERROR: {task.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
