from runtime.dependency_graph import (
    build_dependency_graph,
    get_execution_layers,
    topological_sort,
)


def _chain_tasks(count: int) -> list[dict]:
    return [
        {
            "id": f"TASK-{index:04d}",
            "title": f"task {index}",
            "description": "scalability contract",
            "role": "developer",
            "dependencies": [] if index == 0 else [f"TASK-{index - 1:04d}"],
        }
        for index in range(count)
    ]


def _layered_graph(count: int) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for index in range(count):
        task_id = f"TASK-{index:04d}"
        if index == 0:
            graph[task_id] = []
        elif index < 10:
            graph[task_id] = ["TASK-0000"]
        else:
            graph[task_id] = [f"TASK-{index - 10:04d}"]
    return graph


def test_1k_task_chain_preserves_dependency_first_order():
    graph = build_dependency_graph(_chain_tasks(1000))

    order = topological_sort(graph)

    assert len(graph) == 1000
    assert len(order) == 1000
    assert order[0] == "TASK-0000"
    assert order[-1] == "TASK-0999"
    assert order == [f"TASK-{index:04d}" for index in range(1000)]


def test_1k_task_layered_graph_preserves_parallel_execution_layers():
    graph = _layered_graph(1000)

    layers = get_execution_layers(graph)

    assert sum(len(layer) for layer in layers) == 1000
    assert layers[0] == ["TASK-0000"]
    assert layers[1] == [f"TASK-{index:04d}" for index in range(1, 10)]
    assert all(len(layer) == 1 for layer in layers[2:])


def test_1k_task_graph_construction_does_not_mutate_source_definitions():
    tasks = _chain_tasks(1000)
    original_dependencies = [list(task["dependencies"]) for task in tasks]

    graph = build_dependency_graph(tasks)
    graph["TASK-0001"].append("TASK-9999")

    assert [task["dependencies"] for task in tasks] == original_dependencies
