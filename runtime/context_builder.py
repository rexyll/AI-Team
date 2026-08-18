from runtime.task import Task


def build_task_context(
    task: Task,
    all_tasks: dict[str, Task],
) -> dict:

    context = {}

    for dependency_id in task.dependencies:

        dependency = all_tasks.get(
            dependency_id
        )

        if dependency is None:
            continue

        if dependency.status != "completed":
            continue

        context[dependency_id] = {
            "title": dependency.title,
            "role": dependency.role,
            "result": dependency.result,
        }

    return context