from __future__ import annotations

from time import perf_counter

from runtime.dependency_graph import (
    build_dependency_graph,
    get_execution_layers,
    topological_sort,
)
from runtime.dependency_scheduler import DependencyScheduler
from runtime.task import Task


TASK_COUNT = 5_000
MAX_GRAPH_SECONDS = 5.0
MAX_SCHEDULER_SECONDS = 5.0


def _chain_tasks(count: int) -> list[dict]:
    return [
        {
            "id": f"TASK-{index:05d}",
            "title": f"task {index}",
            "description": "5k scalability contract",
            "role": "developer",
            "dependencies": [] if index == 0 else [f"TASK-{index - 1:05d}"],
        }
        for index in range(count)
    ]


def _layered_tasks(count: int) -> list[dict]:
    """Create deterministic 50-wide layers with one root."""
    width = 50
    tasks: list[dict] = []
    for index in range(count):
        task_id = f"TASK-{index:05d}"
        if index == 0:
            dependencies: list[str] = []
        else:
            parent = ((index - 1) // width) * width + 1
            dependencies = [f"TASK-{parent:05d}"]
        tasks.append(
            {
                "id": task_id,
                "title": f"task {index}",
                "description": "5k layered scalability contract",
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
            description="5k scheduler scalability contract",
            role="developer",
        )
        for index in range(count)
    ]


def test_5k_task_chain_scales_topological_sort_and_graph_build():
    tasks = _chain_tasks(TASK_COUNT)

    started = perf_counter()
    graph = build_dependency_graph(tasks)
    order = topological_sort(graph)
    elapsed = perf_counter() - started

    assert len(graph) == TASK_COUNT
    assert len(order) == TASK_COUNT
    assert order[0] == "TASK-00000"
    assert order[-1] == "TASK-04999"
    assert elapsed < MAX_GRAPH_SECONDS


def test_5k_task_layered_graph_preserves_layers_at_scale():
    graph = build_dependency_graph(_layered_tasks(TASK_COUNT))

    started = perf_counter()
    layers = get_execution_layers(graph)
    elapsed = perf_counter() - started

    assert sum(len(layer) for layer in layers) == TASK_COUNT
    assert layers[0] == ["TASK-00000"]
    assert all(len(layer) == 50 for layer in layers[1:-1])
    assert len(layers[-1]) == 49
    assert elapsed < MAX_GRAPH_SECONDS


def test_5k_task_scheduler_returns_every_ready_task_once_without_mutation():
    tasks = _scheduler_tasks(TASK_COUNT)
    before = [(task.status, list(task.status_history), task.error) for task in tasks]

    started = perf_counter()
    scheduler = DependencyScheduler(tasks)
    ready = scheduler.get_ready_tasks()
    elapsed = perf_counter() - started

    assert len(ready) == TASK_COUNT
    assert [task.id for task in ready] == [
        f"TASK-{index:05d}" for index in range(TASK_COUNT)
    ]
    assert [(task.status, list(task.status_history), task.error) for task in tasks] == before
    assert elapsed < MAX_SCHEDULER_SECONDS
