from __future__ import annotations

from runtime.dependency_graph import build_dependency_graph, topological_sort


def _tasks() -> list[dict]:
    return [
        {"id": "TASK-001", "dependencies": []},
        {"id": "TASK-002", "dependencies": ["TASK-001"]},
        {"id": "TASK-003", "dependencies": ["TASK-001"]},
        {"id": "TASK-004", "dependencies": ["TASK-002", "TASK-003"]},
        {"id": "TASK-005", "dependencies": []},
    ]


def _project(graph: dict[str, list[str]], task_ids: set[str]) -> dict[str, list[str]]:
    return {
        task_id: [dependency for dependency in graph[task_id] if dependency in task_ids]
        for task_id in task_ids
    }


def test_incremental_projection_keeps_selected_subgraph_dependency_closed():
    graph = build_dependency_graph(_tasks())
    projected = _project(graph, {"TASK-001", "TASK-002", "TASK-003"})

    assert projected == {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
    }
    assert topological_sort(projected) == ["TASK-001", "TASK-002", "TASK-003"]


def test_incremental_projection_does_not_mutate_source_graph():
    graph = build_dependency_graph(_tasks())
    before = {task_id: list(dependencies) for task_id, dependencies in graph.items()}

    projected = _project(graph, {"TASK-001", "TASK-002"})
    projected["TASK-001"].append("TASK-005")
    projected["TASK-002"].clear()

    assert graph == before


def test_incremental_projection_rejects_partial_dependency_closure():
    graph = build_dependency_graph(_tasks())
    projected = _project(graph, {"TASK-002", "TASK-003"})

    assert projected == {
        "TASK-002": [],
        "TASK-003": [],
    }
    # A production incremental projection must not silently erase missing dependencies.
    assert any(
        dependency not in projected
        for task_id in {"TASK-002", "TASK-003"}
        for dependency in graph[task_id]
    )
