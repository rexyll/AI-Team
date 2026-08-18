VALID_ROLES = {
    "architect",
    "developer",
    "tester",
    "reviewer",
}


def validate_plan(plan: dict) -> None:
    """Validate task structure, roles, dependencies, and dependency cycles."""
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a dictionary")

    if not plan.get("project"):
        raise ValueError("Plan missing project")

    if "tasks" not in plan:
        raise ValueError("Plan missing tasks")

    tasks = plan["tasks"]
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")
    if not tasks:
        raise ValueError("tasks cannot be empty")

    task_ids = set()

    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Each task must be an object")

        task_id = task.get("id")
        if not task_id:
            raise ValueError("Task missing id")

        if task_id in task_ids:
            raise ValueError(f"Duplicate task id: {task_id}")
        task_ids.add(task_id)

        for field in ("title", "description", "role"):
            if not task.get(field):
                raise ValueError(f"Task {task_id} missing {field}")

        role = task["role"]
        if role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{role}' for task {task_id}"
            )

    graph = {}

    for task in tasks:
        task_id = task["id"]
        dependencies = task.get("dependencies", [])

        if not isinstance(dependencies, list):
            raise ValueError(
                f"Dependencies of {task_id} must be a list"
            )

        graph[task_id] = []
        for dependency in dependencies:
            if dependency not in task_ids:
                raise ValueError(
                    f"Task {task_id} depends on unknown task {dependency}"
                )

            if dependency == task_id:
                raise ValueError(
                    f"Task {task_id} cannot depend on itself"
                )

            graph[task_id].append(dependency)

    # Detect indirect dependency cycles using DFS coloring.
    # 0 = unvisited, 1 = visiting, 2 = fully visited.
    colors = {task_id: 0 for task_id in graph}

    def visit(task_id: str, path: list[str]) -> None:
        color = colors[task_id]
        if color == 2:
            return
        if color == 1:
            cycle_start = path.index(task_id)
            cycle = path[cycle_start:] + [task_id]
            raise ValueError(
                "Circular task dependency detected: "
                + " -> ".join(cycle)
            )

        colors[task_id] = 1
        path.append(task_id)
        for dependency in graph[task_id]:
            visit(dependency, path)
        path.pop()
        colors[task_id] = 2

    for task_id in graph:
        if colors[task_id] == 0:
            visit(task_id, [])
