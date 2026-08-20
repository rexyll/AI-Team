from __future__ import annotations

import argparse
import sys

from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_factory import create_agent_router


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

    return project_orchestrator.run(
        requirement
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    requirement = args.requirement

    if requirement is None:
        parser.error(
            "the following arguments are required: requirement"
        )

    try:
        task_manager = run_project(
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