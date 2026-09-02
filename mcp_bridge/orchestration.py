from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


@dataclass(frozen=True)
class MCPTaskSnapshot:
    """Stable, host-owned task projection exposed to MCP clients."""

    id: str
    title: str
    role: str
    status: str
    dependencies: tuple[str, ...]
    error: str | None
    review_round: int
    retry_attempt: int
    max_retries: int
    cancellation_requested: bool

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "role": self.role, "status": self.status, "dependencies": list(self.dependencies), "error": self.error, "review_round": self.review_round, "retry_attempt": self.retry_attempt, "max_retries": self.max_retries, "cancellation_requested": self.cancellation_requested}


class MCPOrchestrationBoundary:
    """Controlled MCP boundary over host task/agent orchestration state."""

    def __init__(self, task_manager: TaskManager, *, agent_router: Any | None = None, workflow_factory: Callable[[str], Any] | None = None, workflow_event_log: WorkflowEventLog | None = None, project_id: str | None = None) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if agent_router is not None and not hasattr(agent_router, "list_agents"):
            raise TypeError("agent_router must expose list_agents() or None")
        if workflow_factory is not None and not callable(workflow_factory):
            raise TypeError("workflow_factory must be callable or None")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        self._task_manager = task_manager
        self._agent_router = agent_router
        self._workflow_factory = workflow_factory
        self._workflow_event_log = workflow_event_log
        self._project_id = project_id.strip() if isinstance(project_id, str) else project_id
        self._execution_locks: dict[str, Lock] = {}
        self._execution_locks_guard = Lock()
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._idempotency_guard = Lock()

    @classmethod
    def from_orchestrator(cls, orchestrator: Any) -> "MCPOrchestrationBoundary":
        """Bind MCP to an already constructed production Orchestrator."""
        if orchestrator is None:
            raise TypeError("orchestrator must not be None")
        task_manager = getattr(orchestrator, "task_manager", None)
        agent_router = getattr(orchestrator, "agent_router", None)
        execute_task = getattr(orchestrator, "execute_task", None)
        if not isinstance(task_manager, TaskManager):
            raise TypeError("orchestrator must expose a TaskManager")
        if agent_router is None or not callable(getattr(agent_router, "list_agents", None)):
            raise TypeError("orchestrator must expose an AgentRouter")
        if not callable(execute_task):
            raise TypeError("orchestrator must expose its public task execution entrypoint")
        class _HostWorkflow:
            def __init__(self, host: Any) -> None:
                self._host = host
            def execute(self, task_id: str, *, execution_id: str):
                return self._host.execute_task(task_id, execution_id=execution_id)
        return cls(task_manager, agent_router=agent_router, workflow_factory=lambda _task_id: _HostWorkflow(orchestrator), workflow_event_log=getattr(orchestrator, "workflow_event_log", None), project_id=getattr(orchestrator, "project_id", None))

    @staticmethod
    def _snapshot(task) -> MCPTaskSnapshot:
        return MCPTaskSnapshot(id=task.id, title=task.title, role=task.role, status=task.status, dependencies=tuple(task.dependencies), error=task.error, review_round=task.review_round, retry_attempt=task.retry_attempt, max_retries=task.max_retries, cancellation_requested=task.cancellation_requested)

    @staticmethod
    def _supports_execution_id(execute: Callable[..., Any]) -> bool | None:
        """Return whether a callable accepts execution_id; None means signature is unavailable."""
        try:
            signature = inspect.signature(execute)
        except (TypeError, ValueError):
            return None
        parameter = signature.parameters.get("execution_id")
        if parameter is not None:
            return parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        return any(item.kind == inspect.Parameter.VAR_KEYWORD for item in signature.parameters.values())

    def list_tasks(self) -> list[dict[str, Any]]:
        return [self._snapshot(task).as_dict() for task in self._task_manager.get_all_tasks()]

    def get_task(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        return self._snapshot(self._task_manager.get_task(task_id.strip())).as_dict()

    def ready_tasks(self) -> list[dict[str, Any]]:
        return [self._snapshot(task).as_dict() for task in self._task_manager.get_ready_tasks()]

    def agents(self) -> list[dict[str, Any]]:
        if self._agent_router is None:
            return []
        agents = self._agent_router.list_agents()
        return [{"role": role, "registered": agents[role] is not None} for role in sorted(agents)]

    def workflow_capabilities(self) -> dict[str, bool]:
        observable = self._workflow_event_log is not None and bool(self._project_id)
        return {"task_read": True, "agent_read": self._agent_router is not None, "workflow_execute": self._workflow_factory is not None, "workflow_cancel": False, "execution_observability": observable, "execution_status": observable, "execution_idempotency": observable}

    def _mcp_events(self) -> list[WorkflowEvent]:
        if self._workflow_event_log is None or not self._project_id:
            return []
        return [event for event in self._workflow_event_log.list_for_project(self._project_id) if event.payload.get("source") == "mcp"]

    def execution_history(self, task_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if self._workflow_event_log is None or not self._project_id:
            return []
        events = self._workflow_event_log.list_for_task(task_id.strip())
        result: list[dict[str, Any]] = []
        for event in events:
            if event.project_id != self._project_id or event.payload.get("source") != "mcp":
                continue
            result.append({"event_type": event.event_type, "occurred_at": event.occurred_at, "execution_id": event.payload.get("execution_id"), "status": event.payload.get("status"), "error_type": event.payload.get("error_type")})
        return result[-limit:]

    def execution_status(self, execution_id: str) -> dict[str, Any]:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError("execution_id must be a non-empty string")
        normalized_id = execution_id.strip()
        events = [event for event in self._mcp_events() if event.payload.get("execution_id") == normalized_id]
        if not events:
            raise KeyError(f"Unknown execution id: {normalized_id}")
        requested = next((event for event in events if event.event_type == "mcp_task_execution_requested"), events[0])
        completed = next((event for event in events if event.event_type == "mcp_task_execution_completed"), None)
        failed = next((event for event in events if event.event_type == "mcp_task_execution_failed"), None)
        status = "completed" if completed is not None else "failed" if failed is not None else "active"
        result: dict[str, Any] = {"execution_id": normalized_id, "task_id": requested.task_id, "status": status, "started_at": requested.occurred_at}
        if completed is not None:
            result["completed_at"] = completed.occurred_at
            result["task_status"] = completed.payload.get("status")
        if failed is not None:
            result["completed_at"] = failed.occurred_at
            result["error_type"] = failed.payload.get("error_type")
        return result

    def _execution_lock(self, task_id: str) -> Lock:
        with self._execution_locks_guard:
            lock = self._execution_locks.get(task_id)
            if lock is None:
                lock = Lock()
                self._execution_locks[task_id] = lock
            return lock

    def _emit_execution_event(self, event_type: str, task_id: str, execution_id: str, *, payload: dict[str, Any] | None = None) -> None:
        if self._workflow_event_log is None or not self._project_id:
            return
        self._workflow_event_log.append(WorkflowEvent(event_id=str(uuid4()), event_type=event_type, project_id=self._project_id, task_id=task_id, occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), payload={"execution_id": execution_id, "source": "mcp", **(payload or {})}))

    def _find_idempotent_execution(self, idempotency_key: str) -> tuple[str, str] | None:
        existing = self._idempotency.get(idempotency_key)
        if existing is not None:
            return existing
        for event in reversed(self._mcp_events()):
            if event.event_type != "mcp_task_execution_requested":
                continue
            if event.payload.get("idempotency_key") == idempotency_key:
                execution_id = event.payload.get("execution_id")
                if isinstance(execution_id, str) and execution_id:
                    return event.task_id, execution_id
        return None

    def _resolve_idempotent_execution(self, task_id: str, execution_id: str) -> dict[str, Any]:
        status = self.execution_status(execution_id)
        if status["status"] == "completed":
            return {**self._snapshot(self._task_manager.get_task(task_id)).as_dict(), "execution_id": execution_id}
        if status["status"] == "failed":
            raise RuntimeError(f"Idempotent execution {execution_id} already failed")
        raise RuntimeError(f"Idempotent execution {execution_id} is already active")

    def execute_task(self, task_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        if self._workflow_factory is None:
            raise RuntimeError("MCP workflow execution is not configured")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        normalized_id = task_id.strip()
        normalized_key = idempotency_key.strip() if isinstance(idempotency_key, str) else idempotency_key
        if normalized_key is not None and not normalized_key:
            raise ValueError("idempotency_key must be a non-empty string or None")
        if normalized_key is not None and (self._workflow_event_log is None or not self._project_id):
            raise RuntimeError("idempotency requires execution observability")
        if normalized_key is not None:
            with self._idempotency_guard:
                existing = self._find_idempotent_execution(normalized_key)
                if existing is not None:
                    existing_task_id, existing_execution_id = existing
                    if existing_task_id != normalized_id:
                        raise ValueError("idempotency_key is already bound to a different task")
                    return self._resolve_idempotent_execution(normalized_id, existing_execution_id)
        task = self._task_manager.ensure_executable(normalized_id)
        if task.status != "ready":
            raise RuntimeError(f"Task {normalized_id} is already active with status {task.status}")
        lock = self._execution_lock(normalized_id)
        if not lock.acquire(blocking=False):
            raise RuntimeError(f"Task {normalized_id} is already being executed")
        execution_id = str(uuid4())
        if normalized_key is not None:
            with self._idempotency_guard:
                existing = self._find_idempotent_execution(normalized_key)
                if existing is not None:
                    lock.release()
                    existing_task_id, existing_execution_id = existing
                    if existing_task_id != normalized_id:
                        raise ValueError("idempotency_key is already bound to a different task")
                    return self._resolve_idempotent_execution(normalized_id, existing_execution_id)
                self._idempotency[normalized_key] = (normalized_id, execution_id)
        try:
            task = self._task_manager.get_task(normalized_id)
            if task.status != "ready":
                raise RuntimeError(f"Task {normalized_id} is already active with status {task.status}")
            request_payload = {"idempotency_key": normalized_key} if normalized_key is not None else None
            self._emit_execution_event("mcp_task_execution_requested", normalized_id, execution_id, payload=request_payload)
            workflow = self._workflow_factory(normalized_id)
            execute = getattr(workflow, "execute", None)
            if not callable(execute):
                raise TypeError("workflow factory must return an object exposing execute(task_id)")
            supports_execution_id = self._supports_execution_id(execute)
            if supports_execution_id is True or supports_execution_id is None:
                task = execute(normalized_id, execution_id=execution_id)
            else:
                task = execute(normalized_id)
            snapshot = self._snapshot(task).as_dict()
            self._emit_execution_event("mcp_task_execution_completed", normalized_id, execution_id, payload={"status": snapshot["status"]})
            return {**snapshot, "execution_id": execution_id}
        except Exception as exc:
            self._emit_execution_event("mcp_task_execution_failed", normalized_id, execution_id, payload={"error_type": type(exc).__name__})
            raise
        finally:
            lock.release()
