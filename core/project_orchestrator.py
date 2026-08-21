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
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory


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

    @staticmethod
    def _restore_tool_execution_history(
        task_manager: TaskManager,
        history: ToolExecutionHistory | None,
    ) -> None:
        """Rehydrate the project-level history into each task's runtime context."""
        if history is None:
            return

        tasks = {task.id: task for task in task_manager.get_all_tasks()}
        records_by_task: dict[str, list[dict[str, Any]]] = {}
        for record in history.to_dict():
            task_id = record.get("task_id")
            if not isinstance(task_id, str) or task_id not in tasks:
                raise ValueError(
                    f"persisted tool execution history references unknown task: {task_id}"
                )
            records_by_task.setdefault(task_id, []).append(record)

        for task_id, task in tasks.items():
            if task_id in records_by_task:
                task.context["tool_execution_history"] = records_by_task[task_id]

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

    def execute(
        self,
        task_manager: TaskManager,
        *,
        state_change_hook: Callable[[TaskManager], None] | None = None,
    ) -> ProjectResult:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if state_change_hook is not None and not callable(state_change_hook):
            raise TypeError("state_change_hook must be callable or None")

        self.last_task_manager = task_manager
        orchestrator = self.create_orchestrator(task_manager)
        set_hook = getattr(orchestrator, "set_state_change_hook", None)
        if state_change_hook is not None and callable(set_hook):
            set_hook(state_change_hook)
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

    def resume_persisted(
        self,
        project_id: str,
        adapter: ProjectPersistenceAdapter,
    ) -> ProjectResult:
        """Restore persisted project state without starting execution.

        Persisted plans are treated as recovery metadata rather than newly
        generated planner output. The persistence boundary is responsible for
        loading and validating the snapshot; recovery must remain compatible
        with older snapshots whose plan metadata is intentionally minimal.
        """
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")

        snapshot = adapter.load(project_id)
        self.last_plan = snapshot.plan
        self.last_task_manager = snapshot.task_manager
        self._restore_tool_execution_history(
            snapshot.task_manager,
            snapshot.tool_execution_history,
        )
        self.last_result = snapshot.result

        return snapshot.result or ProjectResult.from_task_manager(
            snapshot.task_manager,
            project=(snapshot.plan or {}).get("project")
            if snapshot.plan
            else None,
        )

    def audit_persisted(
        self,
        project_id: str,
        adapter: ProjectPersistenceAdapter,
    ) -> ToolExecutionAudit:
        """Return the canonical read-only audit view for a persisted project."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        return adapter.audit(project_id)

    def continue_persisted(
        self,
        project_id: str,
        adapter: ProjectPersistenceAdapter,
    ) -> ProjectResult:
        """Restore a persisted project and execute only its unfinished work.

        Continuation never invokes the planner or rebuilds the TaskManager.
        The persisted plan, TaskManager, and tool execution history are restored
        first, then the canonical project execution path is used. Each
        execution boundary checkpoints the restored runtime state, and the
        final result is persisted only when the final checkpoint did not already
        capture the same authoritative snapshot.

        Persisted plans are recovery metadata. They are not re-submitted to the
        planner validator during continuation so legacy/minimal plan metadata can
        still be recovered while the persistence adapter remains authoritative
        for snapshot integrity.
        """
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")

        snapshot = adapter.load(project_id)
        self.last_plan = snapshot.plan
        self.last_task_manager = snapshot.task_manager
        self._restore_tool_execution_history(
            snapshot.task_manager,
            snapshot.tool_execution_history,
        )
        project_name = None
        if self.last_plan is not None:
            value = self.last_plan.get("project")
            if isinstance(value, str):
                project_name = value

        last_checkpoint: tuple[tuple[tuple[str, str], ...], ProjectResult] | None = None

        def persist_checkpoint(manager: TaskManager) -> None:
            nonlocal last_checkpoint
            checkpoint_result = ProjectResult.from_task_manager(
                manager,
                project=project_name,
            )
            task_states = tuple(
                (task.id, task.status)
                for task in manager.get_all_tasks()
            )
            adapter.update(
                project_id,
                plan=self.last_plan,
                task_manager=manager,
                result=checkpoint_result,
            )
            last_checkpoint = (task_states, checkpoint_result)

        result = self.execute(
            snapshot.task_manager,
            state_change_hook=persist_checkpoint,
        )
        final_states = tuple(
            (task.id, task.status)
            for task in self.last_task_manager.get_all_tasks()
        )
        if last_checkpoint != (final_states, result):
            adapter.update(
                project_id,
                plan=self.last_plan,
                task_manager=self.last_task_manager,
                result=result,
            )
        return result

    def run(self, requirement: str) -> ProjectResult:
        plan = self.create_plan(requirement)
        task_manager = self.build_task_manager(plan)
        return self.execute(task_manager)
