from runtime.task import Task


def load_tasks(plan: dict) -> list[Task]:

    tasks = []

    for item in plan["tasks"]:

        task = Task(
            id=item["id"],
            title=item["title"],
            description=item["description"],
            role=item["role"],
            dependencies=item.get(
                "dependencies",
                [],
            ),
        )

        tasks.append(task)

    return tasks