from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.analyst import run_quality_checked_analysis
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_factory import create_agent_router
from runtime.clarification_session import ClarificationSession, prompt_for_answers
from runtime.dashboard_cli import write_dashboard
from runtime.model_cost import ModelCostRateRegistry
from runtime.model_usage import ModelUsageLedger
from runtime.plan_constraints import extract_required_paths
from runtime.static_gate import run_static_gate
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
    parser.add_argument(
        "--static-gate", action="store_true",
        help="Require offline Python lint/type checks before packaging; unavailable checks block delivery.",
    )
    parser.add_argument("--save-state", metavar="DIR", help="Save project state in a new directory for later requirement changes.")
    parser.add_argument("--from-state", metavar="DIR", help="Source state directory for --apply-change (left unchanged).")
    parser.add_argument("--apply-change", metavar="PATH", help="Apply a UTF-8 requirement change file, then execute the revised task graph.")
    parser.add_argument(
        "--requirement-input",
        metavar="PATH",
        default=None,
        help="Read the requirement from a UTF-8 text file or a directory of .md/.markdown/.txt files (merged in path order) instead of a CLI string.",
    )
    return parser


_REQUIREMENT_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
_MAX_REQUIREMENT_CHARS = 120_000
_SKIPPED_INPUT_DIR_NAMES = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".pytest_cache"}


def _read_requirement_file(path: Path, label: str) -> str:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"requirement file {label} is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"requirement file {label} cannot be read: {exc}") from exc
    if not content.strip():
        raise ValueError(f"requirement file {label} is empty")
    return content.rstrip()


def load_requirement_input(raw_path: str) -> str:
    """Load requirement text from a UTF-8 file or a directory of text files.

    A directory is searched recursively for ``.md``/``.markdown``/``.txt``
    files; hidden files, common tool directories and symlinks are skipped,
    and surviving files are merged in lexicographic path order, each
    introduced by a header naming the file. The merged text must stay under
    _MAX_REQUIREMENT_CHARS so the requirement cannot silently exceed the
    analyst/planner context budget.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("requirement input path cannot be empty")
    path = Path(raw_path)
    if not path.exists():
        raise ValueError(f"requirement input does not exist: {raw_path}")
    if path.is_file():
        return _read_requirement_file(path, path.name)
    if not path.is_dir():
        raise ValueError(f"requirement input is not a regular file or directory: {raw_path}")

    candidates: list[Path] = []
    for candidate in path.rglob("*"):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if candidate.suffix.lower() not in _REQUIREMENT_TEXT_EXTENSIONS:
            continue
        parts = candidate.relative_to(path).parts
        if any(part.startswith(".") or part in _SKIPPED_INPUT_DIR_NAMES for part in parts):
            continue
        candidates.append(candidate)
    if not candidates:
        raise ValueError(f"requirement directory contains no .md/.markdown/.txt files: {raw_path}")

    sections: list[str] = []
    total = 0
    for candidate in sorted(candidates, key=lambda item: item.relative_to(path).as_posix()):
        relative = candidate.relative_to(path).as_posix()
        section = f"===== 需求文件：{relative} =====\n\n{_read_requirement_file(candidate, relative)}"
        total += len(section)
        if total > _MAX_REQUIREMENT_CHARS:
            raise ValueError(
                f"requirement input exceeds {_MAX_REQUIREMENT_CHARS} characters: {raw_path}"
            )
        sections.append(section)
    return "\n\n".join(sections).strip()


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
    static_gate: bool = False,
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
    task_manager, result, _cost = run_project(
        requirement,
        projects_base=projects_base,
        clarifications=clarifications,
        strict_acceptance=strict_acceptance,
        **({"static_gate": True} if static_gate else {}),
    )
    if result.success:
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


def _load_cost_rate_registry() -> ModelCostRateRegistry:
    """Load optional per-route cost rates from env (AI_TEAM_COST_RATES_JSON).

    Format: {"provider/model": {"input": usd_per_mtok, "output": usd_per_mtok,
    "request": usd}}. Missing/unparseable config yields an empty registry —
    routes are then reported as unpriced instead of silently dropped.
    """
    raw = os.getenv("AI_TEAM_COST_RATES_JSON", "").strip()
    if not raw:
        return ModelCostRateRegistry()
    try:
        payload = json.loads(raw)
        from runtime.model_cost import ModelCostRate
        from runtime.model_governance import ModelRoute

        rates = {}
        for key, value in payload.items():
            provider, _, model = key.partition("/")
            rates[ModelRoute(provider=provider, model=model)] = ModelCostRate(
                input_usd_per_million_tokens=value.get("input", 0),
                output_usd_per_million_tokens=value.get("output", 0),
                request_usd=value.get("request", 0),
            )
        return ModelCostRateRegistry(rates)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"invalid AI_TEAM_COST_RATES_JSON: {exc}") from exc

def run_project(
    requirement: str,
    *,
    projects_base: str | None = None,
    clarifications: str | None = None,
    strict_acceptance: bool = False,
    static_gate: bool = False,
    save_state: str | None = None,
):
    if save_state is not None and Path(save_state).exists():
        raise FileExistsError("--save-state must name a new directory")
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

    usage_ledger = ModelUsageLedger()
    project_id = f"project-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    rate_registry = _load_cost_rate_registry()
    router = create_agent_router(project_id=project_id, usage_ledger=usage_ledger)
    deliverable_dir = mandated_dirs[0].rsplit("/", 1)[-1] if mandated_dirs else None
    project_orchestrator = ProjectOrchestrator(
        agent_router=router,
        deliverable_dir=deliverable_dir,
        clarifications=clarifications,
        usage_ledger=usage_ledger,
        project_id=project_id,
        cost_rate_registry=rate_registry,
        **({"static_gate": run_static_gate} if static_gate else {}),
    )
    plan = project_orchestrator.create_plan(requirement)
    task_manager = project_orchestrator.build_task_manager(plan)
    if save_state is not None:
        from security import workspace

        metadata: dict[str, Any] = {
            "project_id": project_id, "requirement": requirement,
            "workspace_root": str(workspace.get_default_workspace_root()),
            "folded_prefix": "/".join(workspace.DEFAULT_SANDBOX.folded_prefix) or None,
            "deliverable_dir": deliverable_dir, "static_gate": static_gate,
            "clarifications": clarifications,
            "analysis": project_orchestrator.last_requirement_analysis,
            "changes": [],
        }
        adapter = _create_project_state(save_state, metadata, plan, task_manager)
        result = _execute_saved_project(project_orchestrator, task_manager, adapter, project_id)
    else:
        result = project_orchestrator.execute(task_manager)
    if strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
        report = (getattr(project_orchestrator, "last_acceptance", None) or {}).get("report")
        raise AcceptanceGateError(
            f"验收结论为 FAILED；验收报告: {report or '未知'}"
        )
    return task_manager, result, _cost_summary(project_orchestrator)


def _create_project_state(directory, metadata, plan, manager):
    from runtime.project_persistence import ProjectPersistenceAdapter

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    adapter = ProjectPersistenceAdapter(root / "snapshots")
    adapter.save(metadata["project_id"], plan=plan, task_manager=manager)
    (root / "project.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[State] 项目状态已保存: {root}")
    return adapter


def _execute_saved_project(orchestrator, manager, adapter, project_id):
    def checkpoint(current):
        adapter.update(project_id, plan=orchestrator.last_plan, task_manager=current)

    result = orchestrator.execute(manager, state_change_hook=checkpoint)
    adapter.update(project_id, plan=orchestrator.last_plan, task_manager=manager, result=result)
    return result


def run_change_request(*, change_path: str, from_state: str, save_state: str, static_gate: bool = False):
    from runtime.change_request import prepare_change
    from runtime.project_persistence import ProjectPersistenceAdapter
    from runtime.task import Task

    if Path(save_state).exists():
        raise FileExistsError("--save-state must name a new directory")
    change = Path(change_path).read_text(encoding="utf-8")
    if not change.strip():
        raise ValueError("change file cannot be empty")
    source = Path(from_state)
    metadata = json.loads((source / "project.json").read_text(encoding="utf-8"))
    project_id = metadata["project_id"]
    snapshot = ProjectPersistenceAdapter(source / "snapshots").load(project_id)
    set_default_workspace_root(metadata["workspace_root"], folded_prefix=metadata.get("folded_prefix"))
    ledger = ModelUsageLedger()
    router = create_agent_router(project_id=project_id, usage_ledger=ledger)
    planner_agent = router.get_agent("planner")
    if planner_agent is None:
        raise ValueError("No planner agent is registered")

    def planner(prompt, analysis):
        task = Task(id="PLAN-CHANGE", title="Plan requirement change", description=prompt, role="planner", status="ready")
        task.context["requirement_analysis"] = analysis
        result = planner_agent.run(task)
        if not isinstance(result, dict) or not isinstance(result.get("plan"), dict):
            raise TypeError("PlannerAgent result does not contain a valid plan")
        return result["plan"]

    baseline = json.dumps({
        "original_requirement": metadata["requirement"],
        "clarifications": metadata.get("clarifications"),
        "accepted_changes": [record["change"] for record in metadata.get("changes", [])],
        "previous_specification": metadata.get("analysis"),
    }, ensure_ascii=False)
    proposal = prepare_change(snapshot, requirement=baseline, change=change, analyst=router.get_agent("analyst"), planner=planner)
    static_gate = static_gate or metadata.get("static_gate", False)
    orchestrator = ProjectOrchestrator(
        agent_router=router, project_id=project_id,
        deliverable_dir=metadata.get("deliverable_dir"),
        usage_ledger=ledger, cost_rate_registry=_load_cost_rate_registry(),
        static_gate=run_static_gate if static_gate else None,
    )
    orchestrator.last_plan = proposal.plan
    orchestrator.last_requirement_analysis = proposal.analysis
    metadata["analysis"] = proposal.analysis
    metadata["static_gate"] = static_gate
    metadata["changes"] = [*metadata.get("changes", []), proposal.record]
    adapter = _create_project_state(save_state, metadata, proposal.plan, proposal.task_manager)
    result = _execute_saved_project(orchestrator, proposal.task_manager, adapter, project_id)
    return proposal.task_manager, result, _cost_summary(orchestrator)


def _json_result(task_manager, result, *, cost_summary: dict | None = None) -> str:
    """Serialize the stable CLI result contract without exposing raw runtime objects."""
    payload: dict = {
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
        }
    if cost_summary is not None:
        payload["cost"] = cost_summary
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _cost_summary(orchestrator) -> dict | None:
    report = getattr(orchestrator, "last_cost_report", None)
    if report is None:
        return None
    return report.to_dict()


def _result_exit_code(args, result) -> int:
    # Project failure is the baseline non-zero condition; gates only add
    # stricter verdicts on top of it.
    if not result.success:
        return 1
    if args.static_gate and getattr(result, "static_gate_verdict", None) != "passed":
        return 1
    if args.strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
        return 1
    return 0


def main() -> int:
    _ensure_log_safe_streams()
    parser = build_parser()
    args = parser.parse_args()
    if args.apply_change:
        if not args.from_state or not args.save_state:
            parser.error("--apply-change requires --from-state and --save-state")
        if args.requirement or args.requirement_input or args.interactive or args.resume_session or args.analyze_only or args.clarifications or args.projects_base:
            parser.error("--apply-change uses its saved requirement and workspace; incompatible options supplied")
    elif args.from_state:
        parser.error("--from-state requires --apply-change")
    if args.save_state and (args.interactive or args.resume_session or args.analyze_only):
        parser.error("--save-state is supported only for full delivery or --apply-change")
    if args.requirement_input and args.requirement:
        parser.error("--requirement-input cannot be combined with a positional requirement")
    if args.requirement_input:
        try:
            args.requirement = load_requirement_input(args.requirement_input)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.requirement is None and not (args.interactive or args.resume_session or args.apply_change):
        parser.error("the following arguments are required: requirement")

    if args.interactive or args.resume_session:
        task_manager, result, session = run_interactive_session(
            args.requirement or "",
            session_path=args.session_path,
            resume_path=args.resume_session,
            projects_base=args.projects_base,
            strict_acceptance=args.strict_acceptance,
            **({"static_gate": True} if args.static_gate else {}),
        )
        if task_manager is None:
            return 0
        if args.output == "json":
            print(_json_result(task_manager, result))
        return _result_exit_code(args, result)

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
        if args.apply_change:
            task_manager, result, cost_summary = run_change_request(
                change_path=args.apply_change, from_state=args.from_state,
                save_state=args.save_state, static_gate=args.static_gate,
            )
        else:
            clarifications = read_clarifications(args.clarifications)
            task_manager, result, cost_summary = run_project(
                args.requirement,
                projects_base=args.projects_base,
                clarifications=clarifications,
                strict_acceptance=args.strict_acceptance,
                **({"static_gate": True} if args.static_gate else {}),
                **({"save_state": args.save_state} if args.save_state else {}),
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
        print(_json_result(task_manager, result, cost_summary=cost_summary))
        if args.strict_acceptance and getattr(result, "acceptance_verdict", None) == "failed":
            print("[ACCEPTANCE-GATE] 验收结论为 FAILED：按 --strict-acceptance 以非零码退出。", file=sys.stderr)
            return 1
        return _result_exit_code(args, result)

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
    return _result_exit_code(args, result)


if __name__ == "__main__":
    raise SystemExit(main())
