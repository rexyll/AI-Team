from __future__ import annotations

import pytest

from runtime.dependency_index import DependencyIndex


def _graph() -> dict[str, list[str]]:
    return {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
        "TASK-004": ["TASK-002"],
    }


def test_replace_dependencies_updates_forward_and_reverse_indexes():
    index = DependencyIndex.build(_graph())

    updated = index.with_task_dependencies("TASK-004", ["TASK-003"])

    assert index.dependencies_of("TASK-004") == ("TASK-002",)
    assert index.dependents_of("TASK-002") == ("TASK-004",)
    assert updated.dependencies_of("TASK-004") == ("TASK-003",)
    assert updated.dependents_of("TASK-002") == ()
    assert updated.dependents_of("TASK-003") == ("TASK-004",)


def test_adding_a_task_preserves_existing_index_and_adds_empty_reverse_entry():
    index = DependencyIndex.build(_graph())

    updated = index.with_task_dependencies("TASK-005", ["TASK-001"])

    assert "TASK-005" not in index.dependencies
    assert index.dependents_of("TASK-001") == ("TASK-002", "TASK-003")
    assert updated.dependencies_of("TASK-005") == ("TASK-001",)
    assert updated.dependents_of("TASK-001") == ("TASK-002", "TASK-003", "TASK-005")


def test_replacing_dependencies_rejects_unknown_task_dependency():
    index = DependencyIndex.build(_graph())

    with pytest.raises(ValueError, match="unknown task"):
        index.with_task_dependencies("TASK-004", ["TASK-999"])


def test_replacing_dependencies_rejects_unknown_task_id_type():
    index = DependencyIndex.build(_graph())

    with pytest.raises(TypeError, match="task_id must be a string"):
        index.with_task_dependencies(123, [])


def test_replacing_dependencies_does_not_mutate_input_sequence_or_original_index():
    index = DependencyIndex.build(_graph())
    dependencies = ["TASK-003"]

    updated = index.with_task_dependencies("TASK-004", dependencies)
    dependencies.append("TASK-001")

    assert updated.dependencies_of("TASK-004") == ("TASK-003",)
    assert index.dependencies_of("TASK-004") == ("TASK-002",)
