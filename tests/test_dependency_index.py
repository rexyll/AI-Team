from __future__ import annotations

import pytest

from runtime.dependency_index import DependencyIndex


def _graph() -> dict[str, list[str]]:
    return {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
        "TASK-004": ["TASK-002", "TASK-003"],
        "TASK-005": [],
    }


def test_index_builds_forward_and_reverse_relationships():
    index = DependencyIndex.build(_graph())

    assert index.dependencies_of("TASK-004") == ("TASK-002", "TASK-003")
    assert index.dependents_of("TASK-001") == ("TASK-002", "TASK-003")
    assert index.dependents_of("TASK-002") == ("TASK-004",)
    assert index.dependents_of("TASK-005") == ()


def test_affected_tasks_returns_transitive_dependents():
    index = DependencyIndex.build(_graph())

    assert index.affected_tasks({"TASK-001"}) == {
        "TASK-001", "TASK-002", "TASK-003", "TASK-004"
    }
    assert index.affected_tasks({"TASK-005"}) == {"TASK-005"}


def test_index_does_not_alias_source_dependency_lists():
    graph = _graph()
    index = DependencyIndex.build(graph)

    graph["TASK-001"].append("TASK-005")

    assert index.dependencies_of("TASK-001") == ()
    assert index.dependents_of("TASK-005") == ()


def test_index_rejects_unknown_dependency():
    with pytest.raises(ValueError, match="unknown task"):
        DependencyIndex.build({"TASK-001": ["TASK-999"]})


def test_index_rejects_unknown_task_queries():
    index = DependencyIndex.build(_graph())

    with pytest.raises(KeyError, match="Unknown task id"):
        index.dependencies_of("TASK-999")
    with pytest.raises(KeyError, match="Unknown task id"):
        index.dependents_of("TASK-999")
    with pytest.raises(ValueError, match="Unknown task ids"):
        index.affected_tasks({"TASK-999"})
