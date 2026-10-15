from __future__ import annotations

from time import perf_counter

from runtime.dependency_graph import project_dependency_graph


TASK_COUNT = 5_000
MAX_PROJECTION_SECONDS = 1.0


def _large_graph(count: int) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for index in range(count):
        task_id = f"TASK-{index:05d}"
        if index == 0:
            graph[task_id] = []
        else:
            graph[task_id] = [f"TASK-{index - 1:05d}"]
    return graph


def test_small_projection_scales_with_reachable_subgraph_not_full_graph():
    graph = _large_graph(TASK_COUNT)

    started = perf_counter()
    projected = project_dependency_graph(graph, {"TASK-00009"})
    elapsed = perf_counter() - started

    assert list(projected) == [f"TASK-{index:05d}" for index in range(10)]
    assert elapsed < MAX_PROJECTION_SECONDS


def test_large_projection_retains_full_reachable_chain():
    graph = _large_graph(TASK_COUNT)

    projected = project_dependency_graph(graph, {"TASK-04999"})

    assert len(projected) == TASK_COUNT
    assert projected["TASK-00000"] == []
    assert projected["TASK-04999"] == ["TASK-04998"]
