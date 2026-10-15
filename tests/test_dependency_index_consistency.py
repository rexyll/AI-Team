from __future__ import annotations

from runtime.dependency_graph import build_dependency_graph
from runtime.dependency_index import DependencyIndex


def _graph() -> dict[str, list[str]]:
    return {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
        "TASK-004": ["TASK-002", "TASK-003"],
        "TASK-005": ["TASK-004"],
    }


def _apply(graph: dict[str, list[str]], task_id: str, dependencies: list[str]) -> dict[str, list[str]]:
    updated = {key: list(value) for key, value in graph.items()}
    updated[task_id] = list(dependencies)
    return updated


def test_incremental_update_matches_full_rebuild():
    graph = _graph()
    index = DependencyIndex.build(graph)
    updated_graph = _apply(graph, "TASK-004", ["TASK-003"])

    updated_index = index.with_task_dependencies("TASK-004", ["TASK-003"])
    rebuilt_index = DependencyIndex.build(updated_graph)

    assert updated_index == rebuilt_index


def test_incremental_update_repeatedly_preserves_full_rebuild_equivalence():
    graph = _graph()
    index = DependencyIndex.build(graph)
    mutations = [
        ("TASK-004", ["TASK-003"]),
        ("TASK-002", []),
        ("TASK-005", ["TASK-003"]),
    ]

    for task_id, dependencies in mutations:
        graph = _apply(graph, task_id, dependencies)
        index = index.with_task_dependencies(task_id, dependencies)
        assert index == DependencyIndex.build(graph)


def test_index_equivalence_holds_for_graph_built_from_task_definitions():
    task_definitions = [
        {"id": "TASK-001", "dependencies": []},
        {"id": "TASK-002", "dependencies": ["TASK-001"]},
        {"id": "TASK-003", "dependencies": ["TASK-001"]},
        {"id": "TASK-004", "dependencies": ["TASK-002", "TASK-003"]},
    ]
    graph = build_dependency_graph(task_definitions)

    assert DependencyIndex.build(graph) == DependencyIndex.build({
        task["id"]: list(task["dependencies"]) for task in task_definitions
    })
