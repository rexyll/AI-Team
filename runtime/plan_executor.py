from runtime.dependency_graph import build_dependency_graph, get_execution_layers
from runtime.plan_loader import load_tasks
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan


class PlanExecutor:

    def prepare(self, plan: dict):
        validate_plan(plan)

        tasks = load_tasks(plan)

        graph = build_dependency_graph(
            plan["tasks"]
        )

        layers = get_execution_layers(graph)

        manager = TaskManager(tasks)

        return manager, layers