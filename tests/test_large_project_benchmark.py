from __future__ import annotations

from benchmarks.large_project_benchmark import benchmark, layered_tasks
from runtime.dependency_graph import build_dependency_graph, get_execution_layers, topological_sort


def test_layered_workload_is_deterministic_and_dependency_valid():
    first = layered_tasks(1_000)
    second = layered_tasks(1_000)

    assert first == second
    graph = build_dependency_graph(first)
    order = topological_sort(graph)
    layers = get_execution_layers(graph)

    assert len(order) == 1_000
    assert sum(map(len, layers)) == 1_000
    assert layers[0] == ["TASK-00000", *[f"TASK-{i:05d}" for i in range(1, 50 + 1)]]


def test_benchmark_reports_complete_5k_baseline():
    result = benchmark(5_000)

    assert result.task_count == 5_000
    assert result.layer_count > 0
    assert result.projected_count > 0
    assert result.admitted_count > 0
    assert result.peak_memory_bytes > 0
    assert result.graph_build_s >= 0
    assert result.topo_sort_s >= 0
    assert result.layer_s >= 0
    assert result.projection_s >= 0
    assert result.index_build_s >= 0
    assert result.scheduler_ready_s >= 0
    assert result.admission_s >= 0
