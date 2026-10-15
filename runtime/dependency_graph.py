from collections import defaultdict, deque


def build_dependency_graph(tasks: list[dict]) -> dict[str, list[str]]:
    """
    Build a dependency graph from validated task definitions.

    The graph uses the following representation:

        task_id -> [dependency_task_id, ...]
    """
    graph: dict[str, list[str]] = {}

    for task in tasks:
        task_id = task["id"]
        dependencies = task.get("dependencies", [])
        graph[task_id] = list(dependencies)

    return graph


def project_dependency_graph(
    graph: dict[str, list[str]],
    task_ids: set[str],
) -> dict[str, list[str]]:
    """Return an independent dependency-closed projection of ``graph``.

    Every selected task and every transitive dependency required by it is
    retained. The traversal cost is proportional to the reachable subgraph,
    rather than the size of the complete graph.
    """
    if not isinstance(task_ids, set):
        raise TypeError("task_ids must be a set")
    if not task_ids:
        return {}

    unknown = task_ids - graph.keys()
    if unknown:
        raise ValueError(
            "Unknown task ids: " + ", ".join(sorted(unknown))
        )

    projected_ids: set[str] = set()
    stack = sorted(task_ids, reverse=True)

    while stack:
        task_id = stack.pop()
        if task_id in projected_ids:
            continue
        dependencies = graph.get(task_id)
        if dependencies is None:
            raise ValueError(f"Task {task_id} is not present in graph")
        projected_ids.add(task_id)
        stack.extend(sorted(dependencies, reverse=True))

    projected: dict[str, list[str]] = {}
    pending = sorted(projected_ids, reverse=True)
    ordered_ids: list[str] = []
    seen: set[str] = set()

    while pending:
        task_id = pending.pop()
        if task_id in seen:
            continue
        seen.add(task_id)
        ordered_ids.append(task_id)
        pending.extend(sorted(graph[task_id], reverse=True))

    for task_id in ordered_ids:
        projected[task_id] = list(graph[task_id])

    # Validate the projection while preserving the source graph unchanged.
    topological_sort(projected)
    return projected


def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """Return task IDs in dependency-first topological order."""
    reverse_graph: dict[str, list[str]] = {
        task_id: [] for task_id in graph
    }

    indegree = {
        task_id: len(dependencies)
        for task_id, dependencies in graph.items()
    }

    for task_id, dependencies in graph.items():
        for dependency in dependencies:
            if dependency not in graph:
                raise ValueError(
                    f"Task {task_id} depends on unknown task {dependency}"
                )
            reverse_graph[dependency].append(task_id)

    queue = deque(
        task_id
        for task_id, degree in indegree.items()
        if degree == 0
    )

    result: list[str] = []

    while queue:
        task_id = queue.popleft()
        result.append(task_id)

        for dependent in reverse_graph[task_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(graph):
        raise ValueError("Circular task dependency detected")

    return result


def get_execution_layers(
    graph: dict[str, list[str]],
) -> list[list[str]]:
    """Return dependency-aware execution layers."""
    order = topological_sort(graph)
    layers: dict[str, int] = {}

    for task_id in order:
        dependencies = graph[task_id]
        if not dependencies:
            layers[task_id] = 0
            continue
        layers[task_id] = (
            max(layers[dependency] for dependency in dependencies) + 1
        )

    grouped: dict[int, list[str]] = defaultdict(list)
    for task_id in order:
        grouped[layers[task_id]].append(task_id)

    return [grouped[layer] for layer in sorted(grouped)]