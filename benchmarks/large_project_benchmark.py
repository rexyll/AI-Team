from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import tracemalloc

from runtime.dependency_graph import build_dependency_graph, get_execution_layers, project_dependency_graph, topological_sort
from runtime.dependency_index import DependencyIndex
from runtime.dependency_scheduler import DependencyScheduler
from runtime.resource_execution import ResourceExecutionCoordinator
from runtime.resource_governor import ResourceGovernor, ResourceLimits
from runtime.task import Task


@dataclass(frozen=True)
class BenchmarkResult:
    task_count: int
    graph_build_s: float
    topo_sort_s: float
    layer_s: float
    projection_s: float
    index_build_s: float
    scheduler_ready_s: float
    admission_s: float
    peak_memory_bytes: int
    layer_count: int
    projected_count: int
    admitted_count: int


def layered_tasks(task_count: int, fanout: int = 50) -> list[dict]:
    if task_count <= 0:
        raise ValueError("task_count must be positive")
    if fanout <= 0:
        raise ValueError("fanout must be positive")
    tasks: list[dict] = [{"id": "TASK-00000", "dependencies": []}]
    for index in range(1, task_count):
        anchor = ((index - 1) // fanout) * fanout + 1
        dependency = "TASK-00000" if index <= fanout else f"TASK-{anchor:05d}"
        tasks.append({"id": f"TASK-{index:05d}", "dependencies": [dependency]})
    return tasks


def benchmark(task_count: int, *, fanout: int = 50, admission_limit: int = 64) -> BenchmarkResult:
    task_defs = layered_tasks(task_count, fanout)
    tracemalloc.start()
    started = perf_counter()
    graph = build_dependency_graph(task_defs)
    graph_build_s = perf_counter() - started

    started = perf_counter()
    order = topological_sort(graph)
    topo_sort_s = perf_counter() - started

    started = perf_counter()
    layers = get_execution_layers(graph)
    layer_s = perf_counter() - started

    selected = {task_defs[-1]["id"]}
    started = perf_counter()
    projected = project_dependency_graph(graph, selected)
    projection_s = perf_counter() - started

    started = perf_counter()
    index = DependencyIndex.build(graph)
    index_build_s = perf_counter() - started

    tasks = [
        Task(
            id=task_def["id"],
            title=task_def["id"],
            description="benchmark",
            role="developer",
            dependencies=task_def["dependencies"],
        )
        for task_def in task_defs
    ]
    scheduler = DependencyScheduler(tasks)
    started = perf_counter()
    ready = scheduler.get_ready_tasks()
    scheduler_ready_s = perf_counter() - started

    coordinator = ResourceExecutionCoordinator(
        ResourceGovernor(ResourceLimits(max_concurrent_tasks=admission_limit))
    )
    started = perf_counter()
    admitted = [task for task in ready if coordinator.admit(task) is not None]
    admission_s = perf_counter() - started
    for task in admitted:
        coordinator.finish(task.id)

    _, peak_memory_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(order) == task_count
    assert sum(len(layer) for layer in layers) == task_count
    assert len(projected) == len(projected.keys())
    assert index.dependencies_of(order[-1]) == tuple(graph[order[-1]])

    return BenchmarkResult(
        task_count=task_count,
        graph_build_s=graph_build_s,
        topo_sort_s=topo_sort_s,
        layer_s=layer_s,
        projection_s=projection_s,
        index_build_s=index_build_s,
        scheduler_ready_s=scheduler_ready_s,
        admission_s=admission_s,
        peak_memory_bytes=peak_memory_bytes,
        layer_count=len(layers),
        projected_count=len(projected),
        admitted_count=len(admitted),
    )


def run_baseline() -> list[BenchmarkResult]:
    return [benchmark(size) for size in (1_000, 5_000, 10_000)]


if __name__ == "__main__":
    for result in run_baseline():
        print(result)
