from benchmarks.real_developer.scenarios import (
    independent_implementation_tasks,
    partial_implementation_tasks,
    serial_implementation_tasks,
)


UNSAFE_INLINE_MARKERS = (
    "python -c",
    "powershell inline",
    "temporary scripts",
    "shell chaining",
    "redirection",
)


def test_real_developer_scenarios_use_terminal_policy_compatible_commands() -> None:
    tasks = [
        *independent_implementation_tasks(),
        *partial_implementation_tasks(),
        *serial_implementation_tasks(),
    ]

    for task in tasks:
        description = task.description.lower()
        assert "python -m pytest" in description
        assert all(marker not in description for marker in UNSAFE_INLINE_MARKERS)


def test_serial_scenario_is_explicit_about_final_verification_command() -> None:
    final_task = serial_implementation_tasks()[-1]
    assert "python -m pytest tests/test_helpers.py -q" in final_task.description
    assert "python -c" in final_task.description.lower()
