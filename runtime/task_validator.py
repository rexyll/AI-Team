from __future__ import annotations

from typing import Any


VALID_ROLES = {
    "architect",
    "developer",
    "tester",
    "reviewer",
}

PLAN_REQUIRED_FIELDS = {
    "project",
    "summary",
    "tasks",
}

PLAN_ALLOWED_FIELDS = PLAN_REQUIRED_FIELDS

TASK_REQUIRED_FIELDS = {
    "id",
    "title",
    "description",
    "role",
    "dependencies",
}

TASK_ALLOWED_FIELDS = TASK_REQUIRED_FIELDS


def _require_non_empty_string(
    value: Any,
    field_name: str,
) -> None:
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be a string"
        )

    if not value.strip():
        raise ValueError(
            f"{field_name} cannot be empty"
        )


def _validate_exact_fields(
    data: dict[str, Any],
    required_fields: set[str],
    allowed_fields: set[str],
    object_name: str,
) -> None:
    missing = required_fields - data.keys()

    if missing:
        raise ValueError(
            f"{object_name} missing required fields: "
            + ", ".join(sorted(missing))
        )

    unknown = set(data.keys()) - allowed_fields

    if unknown:
        raise ValueError(
            f"{object_name} contains unknown fields: "
            + ", ".join(sorted(unknown))
        )


def validate_task_schema(
    task: dict[str, Any],
) -> None:
    """
    Validate the schema of a single Planner task.

    This validates structure and types only. Dependency existence
    and dependency cycles are validated by validate_plan().
    """
    if not isinstance(task, dict):
        raise ValueError("Each task must be an object")

    task_id = task.get("id", "<unknown>")

    _validate_exact_fields(
        task,
        TASK_REQUIRED_FIELDS,
        TASK_ALLOWED_FIELDS,
        f"Task {task_id}",
    )

    _require_non_empty_string(
        task["id"],
        f"Task {task_id} id",
    )

    _require_non_empty_string(
        task["title"],
        f"Task {task_id} title",
    )

    _require_non_empty_string(
        task["description"],
        f"Task {task_id} description",
    )

    role = task["role"]

    if not isinstance(role, str):
        raise ValueError(
            f"Task {task_id} role must be a string"
        )

    if role not in VALID_ROLES:
        raise ValueError(
            f"Invalid role '{role}' for task {task_id}"
        )

    dependencies = task["dependencies"]

    if not isinstance(dependencies, list):
        raise ValueError(
            f"Dependencies of {task_id} must be a list"
        )

    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise ValueError(
                f"Dependency of {task_id} must be a string"
            )

        if not dependency.strip():
            raise ValueError(
                f"Dependency of {task_id} cannot be empty"
            )


def validate_plan(plan: dict[str, Any]) -> None:
    """
    Validate the complete Planner output.

    Validation includes:
    - Plan schema
    - Task schema
    - task ID uniqueness
    - dependency existence
    - self dependency
    - direct/indirect dependency cycles
    """
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a dictionary")

    _validate_exact_fields(
        plan,
        PLAN_REQUIRED_FIELDS,
        PLAN_ALLOWED_FIELDS,
        "Plan",
    )

    _require_non_empty_string(
        plan["project"],
        "Plan project",
    )

    _require_non_empty_string(
        plan["summary"],
        "Plan summary",
    )

    tasks = plan["tasks"]

    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")

    if not tasks:
        raise ValueError("tasks cannot be empty")

    task_ids: set[str] = set()

    for task in tasks:
        validate_task_schema(task)

        task_id = task["id"]

        if task_id in task_ids:
            raise ValueError(
                f"Duplicate task id: {task_id}"
            )

        task_ids.add(task_id)

    graph: dict[str, list[str]] = {}

    for task in tasks:
        task_id = task["id"]
        dependencies = task.get("dependencies", [])

        if not isinstance(dependencies, list):
            raise ValueError(
                f"Dependencies of {task_id} must be a list"
            )

        graph[task_id] = []

        seen_dependencies = set()

        for dependency in dependencies:
            if not isinstance(dependency, str):
                raise ValueError(
                    f"Dependencies of {task_id} must contain only strings"
                )

            if not dependency.strip():
                raise ValueError(
                    f"Task {task_id} contains an empty dependency id"
                )

            if dependency in seen_dependencies:
                raise ValueError(
                    f"Task {task_id} contains duplicate dependency {dependency}"
                )

            seen_dependencies.add(dependency)

            if dependency not in task_ids:
                raise ValueError(
                    f"Task {task_id} depends on unknown task {dependency}"
                )

            if dependency == task_id:
                raise ValueError(
                    f"Task {task_id} cannot depend on itself"
                )

            graph[task_id].append(dependency)

    # Detect direct and indirect dependency cycles using DFS coloring.
    #
    # 0 = unvisited
    # 1 = visiting
    # 2 = fully visited
    colors = {
        task_id: 0
        for task_id in graph
    }

    def visit(
        task_id: str,
        path: list[str],
    ) -> None:
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
            visit(
                dependency,
                path,
            )

        path.pop()
        colors[task_id] = 2

    for task_id in graph:
        if colors[task_id] == 0:
            visit(
                task_id,
                [],
            )