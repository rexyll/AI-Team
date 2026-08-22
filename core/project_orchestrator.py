from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4
from datetime import datetime, timezone

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
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter


class ProjectOrchestrator:
    """Project-level orchestration entry point."""

    PLANNER_TASK_ID = "PLAN-001"

    def __init__(self, agent_router: AgentRouter, plan_builder: PlanBuilder | None = None, orchestrator_factory: Callable[[TaskManager, AgentRouter], Orchestrator] | None = None, workflow_event_log: WorkflowEventLog | None = None, project_id: str | None = None):
        if agent_router is None:
            raise ValueError("agent_router cannot be None")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        self.agent_router = agent_router
        self.plan_builder = plan_builder if plan_builder is not None else PlanBuilder()
        self.orchestrator_factory = orchestrator_factory if orchestrator_factory is not None else self._default_orchestrator_factory
        self.last_plan: dict[str, Any] | None = None
        self.last_task_manager: TaskManager | None = None
        self.last_result: ProjectResult | None = None
        self._workflow_event_log = workflow_event_log
        self._project_id = project_id

    @property
    def workflow_event_log(self) -> WorkflowEventLog | None:
        """Return the currently attached in-memory workflow event log, if any."""
        return self._workflow_event_log

    @staticmethod
    def _default_orchestrator_factory(task_manager: TaskManager, agent_router: AgentRouter) -> Orchestrator:
        return Orchestrator(task_manager=task_manager, agent_router=agent_router)

    def _resolved_project_id(self) -> str | None:
        if self._project_id is not None:
            return self._project_id
        if self.last_plan is not None:
            value = self.last_plan.get("project_id")
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _emit_project_event(self, event_type: str, *, payload: dict[str, Any] | None = None) -> None:
        if self._workflow_event_log is None:
            return
        project_id = self._resolved_project_id()
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id is required when workflow_event_log is enabled")
        self._workflow_event_log.append(WorkflowEvent(event_id=str(uuid4()), event_type=event_type, project_id=project_id, task_id=None, occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), payload=payload or {}))

    @staticmethod
    def _restore_tool_execution_history(task_manager: TaskManager, history: ToolExecutionHistory | None) -> None:
        """Rehydrate the canonical project history into task runtime contexts."""
        tasks = {task.id: task for task in task_manager.get_all_tasks()}
        for task in tasks.values():
            task.context.pop("tool_execution_history", None)
        if history is None:
            return
        records_by_task: dict[str, list[dict[str, Any]]] = {}
        for record in history.to_dict():
            task_id = record.get("task_id")
            if not isinstance(task_id, str) or task_id not in tasks:
                raise ValueError(f"persisted tool execution history references unknown task: {task_id}")
            records_by_task.setdefault(task_id, []).append(record)
        for task_id, records in records_by_task.items():
            tasks[task_id].context["tool_execution_history"] = records

    def _rehydrate_workflow_event_log(self, project_id: str, event_persistence: WorkflowEventPersistenceAdapter | None) -> None:
        """Optionally restore the independent workflow event stream for recovery."""
        if event_persistence is None:
            return
        if not isinstance(event_persistence, WorkflowEventPersistenceAdapter):
            raise TypeError("event_persistence must be a WorkflowEventPersistenceAdapter or None")
        self._workflow_event_log = event_persistence.load_log()
        self._project_id = project_id

    def create_plan(self, requirement: str) -> dict[str, Any]:
        if not isinstance(requirement, str):
            raise TypeError("requirement must be a string")
        if not requirement.strip():
            raise ValueError("requirement cannot be empty")
        planner = self.agent_router.get_agent("planner")
        planning_task = Task(id=self.PLANNER_TASK_ID, title="Generate project development plan", description=requirement, role="planner", status="ready")
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

    def execute(self, task_manager: TaskManager, *, state_change_hook: Callable[[TaskManager], None] | None = None) -> ProjectResult:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if state_change_hook is not None and not callable(state_change_hook):
            raise TypeError("state_change_hook must be callable or None")
        self.last_task_manager = task_manager
        orchestrator = self.create_orchestrator(task_manager)
        if self._workflow_event_log is not None:
            orchestrator._workflow_event_log = self._workflow_event_log
            orchestrator._project_id = self._resolved_project_id()
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
        self._emit_project_event("project.resumed", payload={"source": "memory"})
        return self.execute(manager)

    def resume_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter, *, event_persistence: WorkflowEventPersistenceAdapter | None = None) -> ProjectResult:
        """Restore persisted project state without starting execution.

        Workflow events are recovered only when an event persistence adapter is
        explicitly supplied. The event stream remains independent of the
        project snapshot and is never embedded in project persistence.
        """
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        snapshot = adapter.load(project_id)
        self.last_plan = snapshot.plan
        self.last_task_manager = snapshot.task_manager
        self._restore_tool_execution_history(snapshot.task_manager, snapshot.tool_execution_history)
        self.last_result = snapshot.result
        self._rehydrate_workflow_event_log(project_id, event_persistence)
        self._emit_project_event("project.resumed", payload={"source": "persistence", "project_id": project_id})
        return snapshot.result or ProjectResult.from_task_manager(snapshot.task_manager, project=(snapshot.plan or {}).get("project") if snapshot.plan else None)

    def audit_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter) -> ToolExecutionAudit:
        """Return the canonical read-only audit view for a persisted project."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        return adapter.audit(project_id)

    def audit_consistency_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter) -> dict[str, Any]:
        """Return the persisted canonical-vs-task-context audit consistency report."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        return adapter.audit_consistency(project_id)

    def continue_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter, *, event_persistence: WorkflowEventPersistenceAdapter | None = None) -> ProjectResult:
        """Restore a persisted project and execute only its unfinished work."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        snapshot = adapter.load(project_id)
        self.last_plan = snapshot.plan
        self.last_task_manager = snapshot.task_manager
        self._restore_tool_execution_history(snapshot.task_manager, snapshot.tool_execution_history)
        self._rehydrate_workflow_event_log(project_id, event_persistence)
        project_name = None
        if self.last_plan is not None:
            value = self.last_plan.get("project")
            if isinstance(value, str):
                project_name = value

        def persist_boundary(manager: TaskManager) -> None:
            boundary_result = ProjectResult.from_task_manager(manager, project=project_name)
            adapter.update(project_id, plan=self.last_plan, task_manager=manager, result=boundary_result)

        result = self.execute(snapshot.task_manager, state_change_hook=persist_boundary)
        persisted = adapter.load(project_id)
        if persisted.result != result or any(persisted.task_manager.get_task(task.id).status != task.status for task in self.last_task_manager.get_all_tasks()):
            adapter.update(project_id, plan=self.last_plan, task_manager=self.last_task_manager, result=result)
        return result

    def run(self, requirement: str) -> ProjectResult:
        plan = self.create_plan(requirement)
        task_manager = self.build_task_manager(plan)
        return self.execute(task_manager)
