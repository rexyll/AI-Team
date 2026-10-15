from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.analyst import run_quality_checked_analysis
from runtime.clarification_session import ClarificationSession, prompt_for_answers
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_factory import create_agent_router
from runtime.dashboard_cli import write_dashboard
from runtime.plan_constraints import extract_required_paths
from security.workspace import PROJECT_ROOT, set_default_workspace_root


CLI_OUTPUT_MODES = ("text", "json")


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
    return parser


def run_analysis_only(requirement: str, *, clarifications: str | None = None, output_path: str = "requirement_analysis.md"):
    """Run only the requirement analysis and persist the draft specification.

    The file doubles as the clarification worksheet: the customer appends
    answers under the appended 客户答复 section and passes the file back via
    --clarifications for a full delivery run.
    """
    router = create_agent_router()
    analyst = router.get_agent("analyst")
    if analyst is None:
        raise ValueError("No analyst agent is registered")
    result = run_quality_checked_analysis(analyst, requirement=requirement, clarifications=clarifications)
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
    if path is None:
        return None
    clarifications = Path(path).read_text(encoding="utf-8")
    if not clarifications.strip():
        raise ValueError("clarifications file cannot be empty")
    return clarifications


class AcceptanceGateError(RuntimeError):
    """Raised with --strict-acceptance when the acceptance verdict is FAILED."""


def run_project(
    requirement: str,
    *,
    projects_base: str | None = None,
    clarifications: str | None = None,
    strict_acceptance: bool = False,
):
    if not isinstance(requirement, str):
        raise TypeError("requirement must be a string")
    if not requirement.strip():
        raise ValueError("requirement cannot be empty")

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
    else:
        set_default_workspace_root(base)

    router = create_agent_router()
    deliverable_dir = mandated_dirs[0].rsplit("/", 1)[-1] if mandated_dirs else None
    project_orchestrator = ProjectOrchestrator(
        agent_router=router,
        deliverable_dir=deliverable_dir,
        clarifications=clarifications,
    )
    plan = project_orchestrator.create_plan(requirement)
    task_manager = project_orchestrator.build_task_manager(plan)
    result = project_orchestrator.execute(task_manager)
    if strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
        report = (getattr(project_orchestrator, "last_acceptance", None) or {}).get("report")
        raise AcceptanceGateError(
            f"验收结论为 FAILED；验收报告: {report or '未知'}"
        )
    return task_manager, result


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
    if args.requirement is None and not (args.interactive or args.resume_session):
        parser.error("the following arguments are required: requirement")

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
            output_path=args.analysis_output,
        )
        quality = result.data.get("quality") or {}
        print(f"[Analysis] 需求规格草案已写入: {output} (attempts={result.data.get('attempts')}, quality_ok={quality.get('ok')})")
        print("[Analysis] 请在文末『客户答复』章节逐条回答【待确认问题】，再使用 --clarifications 启动完整交付。")
        return 0

    try:
        clarifications = read_clarifications(args.clarifications)
        task_manager, result = run_project(
            args.requirement,
            projects_base=args.projects_base,
            clarifications=clarifications,
            strict_acceptance=args.strict_acceptance,
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
