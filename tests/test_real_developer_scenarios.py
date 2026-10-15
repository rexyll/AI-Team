from benchmarks.real_developer.scenarios import (
    independent_implementation_tasks,
    partial_implementation_tasks,
    serial_implementation_tasks,
)


def _all_tasks():
    return [
        *independent_implementation_tasks(),
        *partial_implementation_tasks(),
        *serial_implementation_tasks(),
    ]


def test_real_developer_scenarios_require_terminal_policy_compatible_verification() -> None:
    for task in _all_tasks():
        if task.status == "completed":
            continue
        description = task.description.lower()
        assert "python -m pytest" in description


def test_real_developer_scenarios_explicitly_discourage_inline_code_commands() -> None:
    for task in _all_tasks():
        if task.status == "completed":
            continue
        description = task.description.lower()
        assert "python -c" in description or "do not use python -c" in description


def test_serial_scenario_is_explicit_about_final_verification_command() -> None:
    final_task = serial_implementation_tasks()[-1]
    description = final_task.description.lower()
    assert "python -m pytest tests/test_helpers.py -q" in description
    assert "do not use python -c" in description


def test_benchmark_reference_read_is_not_a_mandatory_duplicate_call() -> None:
    for task in _all_tasks():
        description = task.description.lower()
        assert "exactly twice" not in description
        assert "do not skip the second read" not in description
