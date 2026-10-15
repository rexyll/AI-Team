from benchmarks.real_developer.scenarios import (
    independent_implementation_tasks,
    partial_implementation_tasks,
    serial_implementation_tasks,
)


def _dependencies(tasks):
    return {task.id: tuple(task.dependencies) for task in tasks}


def test_independent_scenario_has_three_way_parallel_width():
    deps = _dependencies(independent_implementation_tasks())
    assert deps["TASK-A"] == ("ROOT",)
    assert deps["TASK-B"] == ("ROOT",)
    assert deps["TASK-C"] == ("ROOT",)
    assert deps["FINAL"] == ("TASK-A", "TASK-B", "TASK-C")


def test_partial_scenario_has_two_way_width_and_dependent_branch():
    deps = _dependencies(partial_implementation_tasks())
    assert deps["TASK-A"] == ("ROOT",)
    assert deps["TASK-B"] == ("ROOT",)
    assert deps["TASK-C"] == ("TASK-A",)
    assert deps["FINAL"] == ("TASK-B", "TASK-C")


def test_serial_scenario_is_a_single_chain():
    deps = _dependencies(serial_implementation_tasks())
    assert deps["TASK-1"] == ()
    assert deps["TASK-2"] == ("TASK-1",)
    assert deps["TASK-3"] == ("TASK-2",)
    assert deps["TASK-4"] == ("TASK-3",)
