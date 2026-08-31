from __future__ import annotations

from runtime.task import Task


_REFERENCE_READ_REQUIREMENT = (
    "Before editing, inspect the relevant source and test files. "
    "Also read docs/benchmark_reference.md exactly twice as two separate "
    "read_file calls before modification. This repeated read is intentional "
    "controlled benchmark workload; do not skip the second read. Do not look "
    "for tasks.json; the task definition is already provided here. "
    "After editing, run the relevant test command exactly as specified. "
    "Use only repository-safe pytest commands such as `python -m pytest tests/test_helpers.py -q`. "
    "Do NOT use `python -c`, PowerShell inline code, temporary scripts, shell chaining, "
    "redirection, or commands outside the allowed terminal policy."
)


def independent_implementation_tasks() -> list[Task]:
    """Three independent implementations followed by integration."""
    common = _REFERENCE_READ_REQUIREMENT
    return [
        Task("ROOT", "Root", "benchmark root", "developer", status="completed"),
        Task("TASK-A", "Date helper", f"Implement parse_iso_date(value) in app/utils/date_helpers.py and tests in tests/test_date_helpers.py. {common}", "developer", dependencies=["ROOT"]),
        Task("TASK-B", "Name helper", f"Implement normalize_identifier(value) in app/utils/name_helpers.py and tests in tests/test_name_helpers.py. {common}", "developer", dependencies=["ROOT"]),
        Task("TASK-C", "Pagination helper", f"Extend pagination behavior in app/utils/pagination.py with a documented page-count edge case and tests in tests/test_pagination.py. {common}", "developer", dependencies=["ROOT"]),
        Task("FINAL", "Integration", "Review the completed utility changes and tests, run python -m pytest tests -q, and make only minimal integration fixes if needed. Do not use python -c or inline-code commands.", "developer", dependencies=["TASK-A", "TASK-B", "TASK-C"]),
    ]


def partial_implementation_tasks() -> list[Task]:
    """Two-way parallel work with a dependent branch before integration."""
    common = _REFERENCE_READ_REQUIREMENT
    return [
        Task("ROOT", "Root", "benchmark root", "developer", status="completed"),
        Task("TASK-A", "Date helper", f"Implement parse_iso_date(value) in app/utils/date_helpers.py and tests in tests/test_date_helpers.py. {common}", "developer", dependencies=["ROOT"]),
        Task("TASK-B", "Name helper", f"Implement normalize_identifier(value) in app/utils/name_helpers.py and tests in tests/test_name_helpers.py. {common}", "developer", dependencies=["ROOT"]),
        Task("TASK-C", "Extend date helper", f"Extend parse_iso_date from TASK-A with an invalid-input case in app/utils/date_helpers.py and tests in tests/test_date_helpers.py. {common}", "developer", dependencies=["TASK-A"]),
        Task("FINAL", "Integration", "Review all utility changes and run python -m pytest tests -q. Make only minimal integration fixes if needed. Do not use python -c or inline-code commands.", "developer", dependencies=["TASK-B", "TASK-C"]),
    ]


def serial_implementation_tasks() -> list[Task]:
    """Concrete serial workload on the isolated benchmark fixture."""
    common = _REFERENCE_READ_REQUIREMENT
    return [
        Task("TASK-1", "Add ISO date parser", f"Implement parse_iso_date(value) in app/utils/helpers.py. It must accept YYYY-MM-DD and return a datetime.date, and raise ValueError for malformed input. Add tests in tests/test_helpers.py. {common}", "developer"),
        Task("TASK-2", "Add identifier normalizer", f"Implement normalize_identifier(value) in app/utils/helpers.py. It must lowercase, trim surrounding whitespace, replace runs of non-alphanumeric characters with a single hyphen, and strip leading/trailing hyphens. Add tests in tests/test_helpers.py. {common}", "developer", dependencies=["TASK-1"]),
        Task("TASK-3", "Harden pagination", f"Improve paginate in app/utils/helpers.py so an empty input reports zero pages and page/page_size validation remains explicit. Preserve existing valid-page behavior and add regression tests in tests/test_helpers.py. {common}", "developer", dependencies=["TASK-2"]),
        Task("TASK-4", "Final verification", "Review the completed changes in app/utils/helpers.py and tests/test_helpers.py. Run python -m pytest tests/test_helpers.py -q and fix any remaining issue without unrelated refactoring. Do not use python -c or other inline-code commands.", "developer", dependencies=["TASK-3"]),
    ]
