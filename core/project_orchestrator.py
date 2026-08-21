from __future__ import annotations

from typing import Any, Callable

from core.orchestrator import Orchestrator
from core.project_result import ProjectResult
from runtime.agent_router import AgentRouter
from runtime.plan_builder import PlanBuilder
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan


class ProjectOrchestrator:
    """Project-level orchestration entry point."""

    PLANNER_TASK_ID = "PLAN-001"

    def __init__(
        self,
        agent_router: AgentRouter,
        plan_builder: PlanBuilder | None = None,
        orchestrator_factory: Callable[[TaskManager, AgentRouter], Orchestrator] | None = None,
    ):
        if agent_router is None:
            raise ValueError("agent_router cannot be None")

        self.agent_router = agent_router
        self.plan_builder = plan_builder if plan_builder is not None else PlanBuilder()
        self.orchestrator_factory = (
            orchestrator_factory
            if orchestrator_factory is not None
            else self._default_orchestrator_factory
        )
        self.last_plan: dict[str, Any] | None = None
        self.last_task_manager: TaskManager | None = None
        self.last_result: ProjectResult | None = None

    @staticmethod
    def _default_orchestrator_factory(task_manager: TaskManager, agent_router: AgentRouter) -> Orchestrator:
        return Orchestrator(task_manager=task_manager, agent_router=agent_router)

    def create_plan(self, requirement: str) -> dict[str, Any]:
        if not isinstance(requirement, str):
            raise TypeError("requirement must be a string")
        if not requirement.strip():
            raise ValueError("requirement cannot be empty")

        planner = self.agent_router.get_agent("planner")
        planning_task = Task(
            id=self.PLANNER_TASK_ID,
            title="Generate project development plan",
            description=requirement,
            role="planner",
            status="ready",
        )
        result = planner.run(planning_task)
        if not isinstance(result, dict):
            raise TypeError("PlannerAgent must return a dictionary")
        plan = result.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("PlannerAgent result does not contain a valid plan")
        validate_plan(plan)
        self.last_plan = plan
        return plan

    def build_task_manager(self, plan: dict[str, Any]) -> TaskManager:
        if not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary")
        task_manager = self.plan_builder.build_task_manager(plan)
        self.last_task_manager = task_manager
        return task_manager

    def create_orchestrator(self, task_manager: TaskManager) -> Orchestrator:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        return self.orchestrator_factory(task_manager, self.agent_router)

    def execute(self, task_manager: TaskManager) -> ProjectResult:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        self.last_task_manager = task_manager
        orchestrator = self.create_orchestrator(task_manager)
        orchestrator.run()
        project_name = None
        if self.last_plan is not None:
            value = self.last_plan.get("project")
            if isinstance(value, str):
                project_name = value
        result = ProjectResult.from_task_manager(task_manager, project=project_name)
        self.last_result = result
        return result

    def resume(self, task_manager: TaskManager | None = None) -> ProjectResult:
        manager = task_manager if task_manager is not None else self.last_task_manager
        if manager is None:
            raise ValueError("no in-memory task manager is available to resume")
        if not isinstance(manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        return self.execute(manager)

    def resume_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter) -> ProjectResult:
        """Restore persisted project state without starting execution."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")

        snapshot = adapter.load(project_id)
        if snapshot.plan is not None:
            validate_plan(snapshot.plan)
            self.last_plan = snapshot.plan
        else:
            self.last_plan = None

        self.last_task_manager = snapshot.task_manager
        self.last_result = snapshot.result
        return snapshot.result or ProjectResult.from_task_manager(
            snapshot.task_manager,
            project=(snapshot.plan or {}).get("project") if snapshot.plan else None,
        )

    def run(self, requirement: str) -> ProjectResult:
        plan = self.create_plan(requirement)
        task_manager = self.build_task_manager(plan)
        return self.execute(task_manager)
