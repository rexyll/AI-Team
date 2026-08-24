from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_factory import create_agent_router
from runtime.plan_constraints import extract_required_paths
from security.workspace import PROJECT_ROOT, set_default_workspace_root


def _ensure_log_safe_streams() -> None:
    """Make console logging resilient to unencodable characters.

    When output is redirected (pipes, Tee-Object, CI logs), Python falls
    back to the legacy locale codepage (e.g. GBK on Chinese Windows).
    Tool payloads routinely contain characters outside such codepages;
    printing them must degrade gracefully instead of killing a running
    task, so streams are reconfigured to replace unencodable characters.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                # Stream may already be detached (e.g. under test capture).
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Team - AI Software Development Team"
    )

    parser.add_argument(
        "requirement",
        nargs="?",
        help="Project requirement to execute.",
    )

    parser.add_argument(
        "--projects-base",
        default=None,
        help=(
            "Base directory for project sandboxes "
            f"(default: {PROJECT_ROOT})."
        ),
    )

    return parser


def run_project(requirement: str, *, projects_base: str | None = None):
    if not isinstance(requirement, str):
        raise TypeError(
            "requirement must be a string"
        )

    if not requirement.strip():
        raise ValueError(
            "requirement cannot be empty"
        )

    # Structural path-constraint enforcement (9.8): when the requirement
    # mandates an output directory ("所有文件放在 workspace/stringkit/"),
    # redirect the sandbox root so relative tool paths land there by
    # construction. Text-level hints alone failed across two models.
    mandated_dirs = extract_required_paths(requirement)
    base = Path(projects_base) if projects_base else Path(PROJECT_ROOT)
    if mandated_dirs:
        from security.workspace import (
            anchor_workspace_root,
            set_default_workspace_root,
        )

        anchored = anchor_workspace_root(base, mandated_dirs[0])
        set_default_workspace_root(anchored)
        print(
            f"[Workspace] 沙盒根已重定向到需求指定目录: {anchored}"
            f"（产物将物理落位于 {mandated_dirs[0]}/ 之下）"
        )
    else:
        from security.workspace import set_default_workspace_root

        set_default_workspace_root(base)

    router = create_agent_router()

    project_orchestrator = ProjectOrchestrator(
        agent_router=router,
    )

    # The canonical three-step project flow: the orchestrator's run()
    # returns a ProjectResult only, while the CLI reports both the
    # per-task statuses and the project-level result.
    plan = project_orchestrator.create_plan(requirement)
    task_manager = project_orchestrator.build_task_manager(plan)
    result = project_orchestrator.execute(task_manager)

    return task_manager, result


def main() -> int:
    _ensure_log_safe_streams()

    parser = build_parser()
    args = parser.parse_args()

    requirement = args.requirement

    if requirement is None:
        parser.error(
            "the following arguments are required: requirement"
        )

    try:
        task_manager, result = run_project(
            requirement,
            projects_base=args.projects_base,
        )

    except Exception as exc:
        print(
            f"[ERROR] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print("=" * 60)
    print("PROJECT RESULT")
    print("=" * 60)
    print(
        f"success={result.success} "
        f"status={result.status} "
        f"completed={result.completed_tasks}/{result.total_tasks}"
    )

    print()
    print("=" * 60)
    print("FINAL TASK STATUS")
    print("=" * 60)

    for task in task_manager.get_all_tasks():
        print(
            f"{task.id:<12}"
            f"{task.status:<14}"
            f"{task.role:<12}"
            f"{task.title}"
        )

        if task.error:
            print(
                f"    ERROR: {task.error}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )