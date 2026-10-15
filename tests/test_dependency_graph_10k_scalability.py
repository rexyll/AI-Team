from __future__ import annotations

from time import perf_counter

from runtime.dependency_graph import (
    build_dependency_graph,
    get_execution_layers,
    topological_sort,
)
from runtime.dependency_scheduler import DependencyScheduler
from runtime.task import Task


TASK_COUNT = 10_000
MAX_GRAPH_SECONDS = 10.0
MAX_SCHEDULER_SECONDS = 10.0


def _chain_tasks(count: int) -> list[dict]:
    return [
        {
            "id": f"TASK-{index:05d}",
            "title": f"task {index}",
            "description": "10k scalability contract",
            "role": "developer",
            "dependencies": [] if index == 0 else [f"TASK-{index - 1:05d}"],
        }
        for index in range(count)
    ]


def _layered_tasks(count: int) -> list[dict]:
    """Create a deterministic two-level DAG with 201 roots and 9799 dependents."""
    width = 50
    tasks: list[dict] = []
    for index in range(count):
        task_id = f"TASK-{index:05d}"
        if index == 0:
            dependencies: list[str] = []
        else:
            parent = ((index - 1) // width) * width + 1
            if parent == index:
                dependencies = []
            else:
                dependencies = [f"TASK-{parent:05d}"]
        tasks.append(
            {
                "id": task_id,
                "title": f"task {index}",
                "description": "10k layered scalability contract",
                "role": "developer",
                "dependencies": dependencies,
            }
        )
    return tasks


def _scheduler_tasks(count: int) -> list[Task]:
    return [
        Task(
            id=f"TASK-{index:05d}",
            title=f"task {index}",
            description="10k scheduler scalability contract",
            role="developer",
        )
        for index in range(count)
    ]


def test_10k_task_chain_scales_topological_sort_and_graph_build():
    tasks = _chain_tasks(TASK_COUNT)

    started = perf_counter()
    graph = build_dependency_graph(tasks)
    order = topological_sort(graph)
    elapsed = perf_counter() - started

    assert len(graph) == TASK_COUNT
    assert len(order) == TASK_COUNT
    assert order[0] == "TASK-00000"
    assert order[-1] == "TASK-09999"
    assert elapsed < MAX_GRAPH_SECONDS


def test_10k_task_layered_graph_preserves_layers_at_scale():
    graph = build_dependency_graph(_layered_tasks(TASK_COUNT))

    started = perf_counter()
    layers = get_execution_layers(graph)
    elapsed = perf_counter() - started

    assert sum(len(layer) for layer in layers) == TASK_COUNT
    assert len(layers) == 2
    assert len(layers[0]) == 201
    assert "TASK-09999" in layers[-1]
    assert elapsed < MAX_GRAPH_SECONDS


def test_10k_task_scheduler_ready_tasks_at_scale():
    tasks = _scheduler_tasks(TASK_COUNT)

    started = perf_counter()
    scheduler = DependencyScheduler(tasks)
    ready = scheduler.get_ready_tasks()
    elapsed = perf_counter() - started

    assert len(ready) == TASK_COUNT
    assert elapsed < MAX_SCHEDULER_SECONDS
