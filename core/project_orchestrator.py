from __future__ import annotations

from typing import Any, Callable

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.plan_builder import PlanBuilder
from runtime.task import Task
from runtime.task_manager import TaskManager


class ProjectOrchestrator:
    """
    Project-level orchestration entry point.

    ProjectOrchestrator is responsible for the complete lifecycle
    from a user requirement to executable runtime tasks:

        Requirement
            ->
        PlannerAgent
            ->
        validated Plan
            ->
        PlanBuilder
            ->
        TaskManager
            ->
        Orchestrator
            ->
        Task execution

    The lower-level Orchestrator remains responsible only for
    executing an already-created TaskManager.
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
        """
        Initialize ProjectOrchestrator.

        Args:
            agent_router:
                Configured AgentRouter containing at least a planner
                agent and the task-execution agents.

            plan_builder:
                Optional PlanBuilder. A default PlanBuilder is created
                when omitted.

            orchestrator_factory:
                Optional factory used to create the lower-level
                Orchestrator. This is primarily useful for testing.
        """
        if agent_router is None:
            raise ValueError(
                "agent_router cannot be None"
            )

        self.agent_router = agent_router

        self.plan_builder = (
            plan_builder
            if plan_builder is not None
            else PlanBuilder()
        )

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

    def create_plan(
        self,
        requirement: str,
    ) -> dict[str, Any]:
        """
        Generate a validated project plan using PlannerAgent.

        PlannerAgent is intentionally not executed through the normal
        TaskManager/Orchestrator workflow.

        Planner is a project-level agent whose output creates the
        actual runtime task graph.
        """
        if not isinstance(requirement, str):
            raise TypeError(
                "requirement must be a string"
            )

        if not requirement.strip():
            raise ValueError(
                "requirement cannot be empty"
            )

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
            raise TypeError(
                "PlannerAgent must return a dictionary"
            )
        elif isinstance(plan, dict):
            plan.setdefault("summary", planning_task)

        plan = result.get("plan")

        if not isinstance(plan, dict):
            raise ValueError(
                "PlannerAgent result does not contain a valid plan"
            )

        self.last_plan = plan

        return plan

    def build_task_manager(
        self,
        plan: dict[str, Any],
    ) -> TaskManager:
        """
        Convert a validated Planner plan into a TaskManager.
        """
        if not isinstance(plan, dict):
            raise TypeError(
                "plan must be a dictionary"
            )

        task_manager = self.plan_builder.build_task_manager(
            plan
        )

        self.last_task_manager = task_manager

        return task_manager

    def create_orchestrator(
        self,
        task_manager: TaskManager,
    ) -> Orchestrator:
        """
        Create the lower-level task execution Orchestrator.
        """
        if not isinstance(task_manager, TaskManager):
            raise TypeError(
                "task_manager must be a TaskManager"
            )

        return self.orchestrator_factory(
            task_manager,
            self.agent_router,
        )

    def run(
        self,
        requirement: str,
    ) -> TaskManager:
        """
        Plan and execute a complete project.

        The lifecycle is:

            requirement
                ->
            PlannerAgent
                ->
            PlanBuilder
                ->
            TaskManager
                ->
            Orchestrator.run()

        Returns:
            The TaskManager containing the final state of all
            generated project tasks.
        """
        plan = self.create_plan(
            requirement
        )

        task_manager = self.build_task_manager(
            plan
        )

        orchestrator = self.create_orchestrator(
            task_manager
        )

        orchestrator.run()

        return task_manager