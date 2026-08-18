from collections import defaultdict, deque


def build_dependency_graph(tasks: list[dict]) -> dict[str, list[str]]:
    """
    Build a dependency graph from validated task definitions.

    The graph uses the following representation:

        task_id -> [dependency_task_id, ...]

    Example:

        TASK-002 depends on TASK-001

    becomes:

        {
            "TASK-001": [],
            "TASK-002": ["TASK-001"],
        }

    This function expects the task definitions to have already been
    validated by validate_plan().
    """
    graph: dict[str, list[str]] = {}

    for task in tasks:
        task_id = task["id"]
        dependencies = task.get("dependencies", [])

        graph[task_id] = list(dependencies)

    return graph


def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """
    Return task IDs in dependency-first topological order.

    For example:

        TASK-002 -> TASK-001

    produces:

        ["TASK-001", "TASK-002"]

    Raises:
        ValueError:
            If the graph contains a circular dependency.
    """
    # Build reverse edges:
    #
    # dependency -> tasks that depend on it
    #
    # Example:
    #
    # TASK-002 -> TASK-001
    #
    # reverse:
    #
    # TASK-001 -> TASK-002
    reverse_graph: dict[str, list[str]] = {
        task_id: [] for task_id in graph
    }

    # Number of dependencies that each task still needs to complete.
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

    # Tasks without dependencies can execute first.
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
        raise ValueError(
            "Circular task dependency detected"
        )

    return result


def get_execution_layers(
    graph: dict[str, list[str]],
) -> list[list[str]]:
    """
    Return dependency-aware execution layers.

    Tasks in the same layer have no dependency relationship between
    themselves and can potentially execute in parallel.

    Example:

        TASK-001
        TASK-002 -> TASK-001
        TASK-003 -> TASK-001
        TASK-004 -> TASK-002, TASK-003

    produces:

        [
            ["TASK-001"],
            ["TASK-002", "TASK-003"],
            ["TASK-004"],
        ]

    Raises:
        ValueError:
            If the graph contains an unknown dependency or cycle.
    """
    order = topological_sort(graph)

    # Calculate the layer for every task.
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

    # Iterate through topological order so the result is deterministic.
    for task_id in order:
        grouped[layers[task_id]].append(task_id)

    return [
        grouped[layer]
        for layer in sorted(grouped)
    ]