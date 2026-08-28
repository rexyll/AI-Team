from __future__ import annotations

import pytest

from runtime.dependency_graph import (
    build_dependency_graph,
    project_dependency_graph,
    topological_sort,
)


def _tasks() -> list[dict]:
    return [
        {"id": "TASK-001", "dependencies": []},
        {"id": "TASK-002", "dependencies": ["TASK-001"]},
        {"id": "TASK-003", "dependencies": ["TASK-001"]},
        {"id": "TASK-004", "dependencies": ["TASK-002", "TASK-003"]},
        {"id": "TASK-005", "dependencies": []},
    ]


def test_projection_is_transitively_dependency_closed():
    graph = build_dependency_graph(_tasks())
    projected = project_dependency_graph(graph, {"TASK-004"})

    assert projected == {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
        "TASK-004": ["TASK-002", "TASK-003"],
    }
    assert topological_sort(projected) == [
        "TASK-001",
        "TASK-002",
        "TASK-003",
        "TASK-004",
    ]


def test_projection_is_independent_from_source_graph():
    graph = build_dependency_graph(_tasks())
    before = {task_id: list(dependencies) for task_id, dependencies in graph.items()}

    projected = project_dependency_graph(graph, {"TASK-002"})
    projected["TASK-001"].append("TASK-005")
    projected["TASK-002"].clear()

    assert graph == before


def test_projection_rejects_unknown_selected_task():
    graph = build_dependency_graph(_tasks())

    with pytest.raises(ValueError, match="Unknown task ids"):
        project_dependency_graph(graph, {"TASK-999"})


def test_projection_rejects_non_set_selection():
    graph = build_dependency_graph(_tasks())

    with pytest.raises(TypeError, match="task_ids must be a set"):
        project_dependency_graph(graph, ["TASK-002"])


def test_empty_projection_is_empty_graph():
    graph = build_dependency_graph(_tasks())

    assert project_dependency_graph(graph, set()) == {}


def test_projection_preserves_source_cycles_as_rejected_graphs():
    graph = {
        "TASK-001": ["TASK-002"],
        "TASK-002": ["TASK-001"],
    }

    with pytest.raises(ValueError, match="Circular task dependency detected"):
        project_dependency_graph(graph, {"TASK-001"})
