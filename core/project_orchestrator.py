from __future__ import annotations

from typing import Any, Callable

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.plan_builder import PlanBuilder
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan


class ProjectOrchestrator:
    """
    Project-level orchestration entry point.

    ProjectOrchestrator owns the project lifecycle facade:

        Requirement
            -> PlannerAgent
            -> validated Plan
            -> PlanBuilder
            -> TaskManager
            -> Orchestrator
            -> Task execution

    The lower-level Orchestrator remains responsible only for executing
    an already-created TaskManager. ProjectOrchestrator does not duplicate
    dependency scheduling or per-task workflow state transitions.
    """

    PLANNER_TASK_ID = "PLAN-001"

    def __init__(
        self,
        agent_router: AgentRouter,
        plan_builder: PlanBuilder | None = None,
        orchestrator_factory: Callable[
            [TaskManager, AgentRouter],
            Orchestrator,
        ] | None = None,
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

    @staticmethod
    def _default_orchestrator_factory(
        task_manager: TaskManager,
        agent_router: AgentRouter,
    ) -> Orchestrator:
        return Orchestrator(
            task_manager=task_manager,
            agent_router=agent_router,
        )

    def create_plan(self, requirement: str) -> dict[str, Any]:
        """Generate and validate the project task graph."""
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

        # ProjectOrchestrator is the boundary at which Planner output becomes
        # an accepted project plan. Do not expose an invalid plan through
        # last_plan or pass it to the runtime graph builder.
        validate_plan(plan)
        self.last_plan = plan
        return plan

    def build_task_manager(self, plan: dict[str, Any]) -> TaskManager:
        """Convert a validated Planner plan into a TaskManager."""
        if not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary")

        task_manager = self.plan_builder.build_task_manager(plan)
        self.last_task_manager = task_manager
        return task_manager

    def create_orchestrator(self, task_manager: TaskManager) -> Orchestrator:
        """Create the lower-level task execution Orchestrator."""
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")

        return self.orchestrator_factory(
            task_manager,
            self.agent_router,
        )

    def execute(self, task_manager: TaskManager) -> TaskManager:
        """
        Execute an already-built project task graph.

        This is the explicit project-level execution boundary. It delegates
        task scheduling and lifecycle execution to the lower-level
        Orchestrator and does not implement those policies itself.
        """
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")

        self.last_task_manager = task_manager
        orchestrator = self.create_orchestrator(task_manager)
        orchestrator.run()
        return task_manager

    def run(self, requirement: str) -> TaskManager:
        """
        Plan and execute a complete project through the project facade.
        """
        plan = self.create_plan(requirement)
        task_manager = self.build_task_manager(plan)
        return self.execute(task_manager)
