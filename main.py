from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    parser.add_argument("requirement", nargs="?", help="Project requirement to execute.")
    parser.add_argument("--projects-base", default=None, help=f"Base directory for project sandboxes (default: {PROJECT_ROOT}).")
    parser.add_argument("--dashboard", metavar="PATH", default=None, help="Write a self-contained operational dashboard HTML file after execution.")
    parser.add_argument(
        "--output",
        choices=CLI_OUTPUT_MODES,
        default="text",
        help="Output format: text for human-readable output (default), json for machine-readable result output.",
    )
    return parser


def run_project(requirement: str, *, projects_base: str | None = None):
    if not isinstance(requirement, str):
        raise TypeError("requirement must be a string")
    if not requirement.strip():
        raise ValueError("requirement cannot be empty")

    mandated_dirs = extract_required_paths(requirement)
    base = Path(projects_base) if projects_base else Path(PROJECT_ROOT)
    if mandated_dirs:
        from security.workspace import anchor_workspace_root
        anchored = anchor_workspace_root(base, mandated_dirs[0])
        set_default_workspace_root(anchored)
        print(f"[Workspace] 沙盒根已重定向到需求指定目录: {anchored}（产物将物理落位于 {mandated_dirs[0]}/ 之下）")
    else:
        set_default_workspace_root(base)

    router = create_agent_router()
    project_orchestrator = ProjectOrchestrator(agent_router=router)
    plan = project_orchestrator.create_plan(requirement)
    task_manager = project_orchestrator.build_task_manager(plan)
    result = project_orchestrator.execute(task_manager)
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
    if args.requirement is None:
        parser.error("the following arguments are required: requirement")

    try:
        task_manager, result = run_project(args.requirement, projects_base=args.projects_base)
        if args.dashboard:
            project_id = None
            write_dashboard(task_manager.get_all_tasks(), args.dashboard, project_id=project_id)
            if args.output == "text":
                print(f"[Dashboard] 已生成: {Path(args.dashboard)}")
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(_json_result(task_manager, result))
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
