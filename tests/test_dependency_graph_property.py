from __future__ import annotations

import random

from runtime.dependency_graph import (
    build_dependency_graph,
    get_execution_layers,
    topological_sort,
)


def _random_dag(rng: random.Random, task_count: int, edge_probability: float) -> list[dict]:
    """Generate a random DAG by only allowing edges from earlier to later tasks."""
    tasks = [
        {
            "id": f"TASK-{index:04d}",
            "title": f"task {index}",
            "description": "property-based scalability contract",
            "role": "developer",
            "dependencies": [],
        }
        for index in range(task_count)
    ]
    for later in range(1, task_count):
        for earlier in range(later):
            if rng.random() < edge_probability:
                tasks[later]["dependencies"].append(f"TASK-{earlier:04d}")
    return tasks


def _assert_valid_topological_order(graph: dict[str, list[str]], order: list[str]) -> None:
    assert sorted(order) == sorted(graph)
    position = {task_id: index for index, task_id in enumerate(order)}
    for task_id, dependencies in graph.items():
        for dependency in dependencies:
            assert position[dependency] < position[task_id], (
                f"dependency {dependency} must precede {task_id}"
            )


def test_random_dags_preserve_dependency_ordering_and_layers():
    rng = random.Random(20260906)
    for _trial in range(30):
        tasks = _random_dag(rng, rng.randint(2, 80), rng.uniform(0.0, 0.15))
        graph = build_dependency_graph(tasks)

        order = topological_sort(graph)
        _assert_valid_topological_order(graph, order)

        layers = get_execution_layers(graph)
        flattened = [task_id for layer in layers for task_id in layer]
        _assert_valid_topological_order(graph, flattened)

        layer_of = {
            task_id: index for index, layer in enumerate(layers) for task_id in layer
        }
        for task_id, dependencies in graph.items():
            for dependency in dependencies:
                assert layer_of[dependency] < layer_of[task_id]


def test_random_dags_cover_disconnected_and_dense_regions():
    rng = random.Random(42)
    saw_disconnected = False
    saw_multi_layer = False
    for _trial in range(30):
        tasks = _random_dag(rng, rng.randint(2, 60), rng.uniform(0.0, 0.2))
        graph = build_dependency_graph(tasks)
        layers = get_execution_layers(graph)

        if len(layers) > 1:
            saw_multi_layer = True
        if any(len(dependencies) == 0 for dependencies in graph.values()) and len(layers) == 1:
            saw_disconnected = True

        # Every layer only contains tasks whose dependencies are in earlier layers.
        earlier: set[str] = set()
        for layer in layers:
            for task_id in layer:
                assert all(dependency in earlier for dependency in graph[task_id])
            earlier.update(layer)

    assert saw_multi_layer
    assert saw_disconnected
