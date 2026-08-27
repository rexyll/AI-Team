from __future__ import annotations

from runtime.task import Task


def _inspection_requirements() -> str:
    return (
        "Before editing, inspect request/app/utils/helpers.py and "
        "request/tests/test_utils.py. The benchmark intentionally requires "
        "the exact helpers.py read to be repeated as a separate read-only "
        "inspection before modification, so do not skip the second read. "
        "Do not look for tasks.json; the task definition is already provided "
        "here. After editing, run python -m pytest request/tests/test_utils.py -q."
    )


def independent_implementation_tasks() -> list[Task]:
    """Three independent implementations followed by integration."""
    common = _inspection_requirements()
    return [
        Task("ROOT", "Root", "benchmark root", "developer", status="completed"),
        Task(
            "TASK-A",
            "Date helper",
            f"Implement a new parse_iso_date(value) helper in request/app/utils/helpers.py. "
            f"Add focused tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["ROOT"],
        ),
        Task(
            "TASK-B",
            "Name helper",
            f"Implement a new normalize_identifier(value) helper in request/app/utils/helpers.py. "
            f"Add focused tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["ROOT"],
        ),
        Task(
            "TASK-C",
            "Pagination helper",
            f"Extend pagination behavior in request/app/utils/helpers.py with a documented "
            f"page-count edge case and add focused tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["ROOT"],
        ),
        Task(
            "FINAL",
            "Integration",
            "Review the completed utility changes in request/app/utils/helpers.py and request/tests/test_utils.py, run python -m pytest request/tests/test_utils.py -q, and make only minimal integration fixes if needed.",
            "developer",
            dependencies=["TASK-A", "TASK-B", "TASK-C"],
        ),
    ]


def partial_implementation_tasks() -> list[Task]:
    """Two-way parallel work with a dependent branch before integration."""
    common = _inspection_requirements()
    return [
        Task("ROOT", "Root", "benchmark root", "developer", status="completed"),
        Task(
            "TASK-A",
            "Date helper",
            f"Implement parse_iso_date(value) in request/app/utils/helpers.py and tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["ROOT"],
        ),
        Task(
            "TASK-B",
            "Name helper",
            f"Implement normalize_identifier(value) in request/app/utils/helpers.py and tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["ROOT"],
        ),
        Task(
            "TASK-C",
            "Extend date helper",
            f"Extend the parse_iso_date behavior from TASK-A with an invalid-input case and tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["TASK-A"],
        ),
        Task(
            "FINAL",
            "Integration",
            "Review all utility changes in request/app/utils/helpers.py and request/tests/test_utils.py and run python -m pytest request/tests/test_utils.py -q.",
            "developer",
            dependencies=["TASK-B", "TASK-C"],
        ),
    ]


def serial_implementation_tasks() -> list[Task]:
    """Concrete serial workload on the isolated benchmark fixture."""
    common = _inspection_requirements()
    return [
        Task(
            "TASK-1",
            "Add ISO date parser",
            f"Implement parse_iso_date(value) in request/app/utils/helpers.py. "
            f"It must accept YYYY-MM-DD and return a datetime.date, and raise ValueError for malformed input. "
            f"Add tests in request/tests/test_utils.py. {common}",
            "developer",
        ),
        Task(
            "TASK-2",
            "Add identifier normalizer",
            f"Implement normalize_identifier(value) in request/app/utils/helpers.py. "
            f"It must lowercase, trim surrounding whitespace, replace runs of non-alphanumeric characters with a single hyphen, and strip leading/trailing hyphens. "
            f"Add tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["TASK-1"],
        ),
        Task(
            "TASK-3",
            "Harden pagination",
            f"Improve paginate in request/app/utils/helpers.py so an empty input reports zero pages and page/page_size validation remains explicit. "
            f"Preserve existing behavior for valid pages and add regression tests in request/tests/test_utils.py. {common}",
            "developer",
            dependencies=["TASK-2"],
        ),
        Task(
            "TASK-4",
            "Final verification",
            "Review the completed changes in request/app/utils/helpers.py and request/tests/test_utils.py. Run python -m pytest request/tests/test_utils.py -q and fix any remaining issue without unrelated refactoring.",
            "developer",
            dependencies=["TASK-3"],
        ),
    ]
