from __future__ import annotations

import argparse
import sys

from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_factory import create_agent_router


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

    return parser


def run_project(requirement: str):
    if not isinstance(requirement, str):
        raise TypeError(
            "requirement must be a string"
        )

    if not requirement.strip():
        raise ValueError(
            "requirement cannot be empty"
        )

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
            requirement
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