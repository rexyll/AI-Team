VALID_ROLES = {
    "architect",
    "developer",
    "tester",
    "reviewer",
}


def validate_plan(plan: dict) -> None:
    if not isinstance(plan, dict):
        raise ValueError(
            "Plan must be a dictionary"
        )

    if not plan.get("project"):
        raise ValueError(
            "Plan missing project"
        )

    if "tasks" not in plan:
        raise ValueError(
            "Plan missing tasks"
        )

    tasks = plan["tasks"]

    if not isinstance(tasks, list):
        raise ValueError(
            "tasks must be a list"
        )

    if not tasks:
        raise ValueError(
            "tasks cannot be empty"
        )

    task_ids = set()

    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError(
                "Each task must be an object"
            )

        task_id = task.get("id")

        if not task_id:
            raise ValueError(
                "Task missing id"
            )

        if task_id in task_ids:
            raise ValueError(
                f"Duplicate task id: {task_id}"
            )

        task_ids.add(task_id)

        for field in (
            "title",
            "description",
            "role",
        ):
            if not task.get(field):
                raise ValueError(
                    f"Task {task_id} missing {field}"
                )

        role = task["role"]

        if role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{role}' "
                f"for task {task_id}"
            )

    # 第二遍检查依赖关系
    for task in tasks:
        dependencies = task.get(
            "dependencies",
            [],
        )

        if not isinstance(dependencies, list):
            raise ValueError(
                f"Dependencies of "
                f"{task['id']} must be a list"
            )

        for dependency in dependencies:
            if dependency not in task_ids:
                raise ValueError(
                    f"Task {task['id']} "
                    f"depends on unknown task "
                    f"{dependency}"
                )

            if dependency == task["id"]:
                raise ValueError(
                    f"Task {task['id']} "
                    f"cannot depend on itself"
                )