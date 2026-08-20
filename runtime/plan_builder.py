from __future__ import annotations

from typing import Any

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan


class PlanBuilder:
    """
    Convert a validated Planner output into runtime Task objects.

    PlanBuilder is responsible for the boundary between:

        Planner output
            ->
        Runtime Task objects

    It does not execute tasks and does not modify the Planner output.
    """

    def build_tasks(
        self,
        plan: dict[str, Any],
    ) -> list[Task]:
        """
        Build runtime Task objects from a Planner plan.

        Args:
            plan:
                Planner output dictionary.

        Returns:
            A list of Task objects with initial status ``pending``.

        Raises:
            TypeError:
                If plan is not a dictionary.

            ValueError:
                If the plan does not satisfy the Planner schema.
        """
        if not isinstance(plan, dict):
            raise TypeError(
                "plan must be a dictionary"
            )

        # Validate the complete plan before constructing runtime objects.
        validate_plan(plan)

        tasks: list[Task] = []

        for task_data in plan["tasks"]:
            task = Task(
                id=task_data["id"],
                title=task_data["title"],
                description=task_data["description"],
                role=task_data["role"],
                status="pending",
                dependencies=list(
                    task_data["dependencies"]
                ),
            )

            tasks.append(task)

        return tasks

    def build_task_manager(
        self,
        plan: dict[str, Any],
    ) -> TaskManager:
        """
        Build a TaskManager directly from a Planner plan.

        Args:
            plan:
                Planner output dictionary.

        Returns:
            A TaskManager containing all generated Tasks.
        """
        tasks = self.build_tasks(plan)

        return TaskManager(tasks)


def build_tasks(
    plan: dict[str, Any],
) -> list[Task]:
    """
    Convenience function for converting a Planner plan into Tasks.
    """
    return PlanBuilder().build_tasks(plan)


def build_task_manager(
    plan: dict[str, Any],
) -> TaskManager:
    """
    Convenience function for converting a Planner plan into a TaskManager.
    """
    return PlanBuilder().build_task_manager(plan)