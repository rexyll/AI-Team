from __future__ import annotations

from time import perf_counter

from runtime.dependency_graph import build_dependency_graph
from runtime.dependency_index import DependencyIndex


TASK_COUNT = 5_000
MAX_BUILD_SECONDS = 5.0


def _chain_graph(count: int) -> dict[str, list[str]]:
    return {
        f"TASK-{index:05d}": [] if index == 0 else [f"TASK-{index - 1:05d}"]
        for index in range(count)
    }


def test_5k_index_build_and_queries_scale():
    graph = _chain_graph(TASK_COUNT)

    started = perf_counter()
    index = DependencyIndex.build(graph)
    elapsed = perf_counter() - started

    assert elapsed < MAX_BUILD_SECONDS
    assert index.dependencies_of("TASK-04999") == ("TASK-04998",)
    assert index.dependents_of("TASK-00000") == ("TASK-00001",)
    assert len(index.affected_tasks({"TASK-00000"})) == TASK_COUNT


def test_5k_index_matches_graph_reverse_relationships():
    graph = build_dependency_graph([
        {"id": task_id, "dependencies": dependencies}
        for task_id, dependencies in _chain_graph(TASK_COUNT).items()
    ])
    index = DependencyIndex.build(graph)

    for index_value in (0, 1, 2_500, 4_999):
        task_id = f"TASK-{index_value:05d}"
        expected_dependencies = tuple(graph[task_id])
        expected_dependents = tuple(
            candidate
            for candidate, dependencies in graph.items()
            if task_id in dependencies
        )
        assert index.dependencies_of(task_id) == expected_dependencies
        assert index.dependents_of(task_id) == expected_dependents
