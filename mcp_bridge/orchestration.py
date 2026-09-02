from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

from runtime.task_manager import TaskManager


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
        return {
            "id": self.id,
            "title": self.title,
            "role": self.role,
            "status": self.status,
            "dependencies": list(self.dependencies),
            "error": self.error,
            "review_round": self.review_round,
            "retry_attempt": self.retry_attempt,
            "max_retries": self.max_retries,
            "cancellation_requested": self.cancellation_requested,
        }


class MCPOrchestrationBoundary:
    """Controlled MCP boundary over the host task/agent orchestration state.

    The boundary deliberately returns projections instead of Task/agent
    objects. Runtime execution is enabled only through an explicit host-owned
    workflow factory. A per-task execution lock prevents duplicate concurrent
    MCP starts while leaving different tasks independently executable.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        *,
        agent_router: Any | None = None,
        workflow_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if agent_router is not None and not hasattr(agent_router, "list_agents"):
            raise TypeError("agent_router must expose list_agents() or be None")
        if workflow_factory is not None and not callable(workflow_factory):
            raise TypeError("workflow_factory must be callable or None")
        self._task_manager = task_manager
        self._agent_router = agent_router
        self._workflow_factory = workflow_factory
        self._execution_locks: dict[str, Lock] = {}
        self._execution_locks_guard = Lock()

    @classmethod
    def from_orchestrator(cls, orchestrator: Any) -> "MCPOrchestrationBoundary":
        """Bind MCP to an already constructed production Orchestrator.

        No TaskManager, AgentRouter, agents, or workflow runtime is created by
        this adapter. The supplied Orchestrator remains the sole execution
        owner; its existing retry, recovery, resource, checkpoint, routing, and
        workflow semantics are reused unchanged.
        """
        if orchestrator is None:
            raise TypeError("orchestrator must not be None")
        task_manager = getattr(orchestrator, "task_manager", None)
        agent_router = getattr(orchestrator, "agent_router", None)
        execute_task = getattr(orchestrator, "_execute_task", None)
        if not isinstance(task_manager, TaskManager):
            raise TypeError("orchestrator must expose a TaskManager")
        if agent_router is None or not callable(getattr(agent_router, "list_agents", None)):
            raise TypeError("orchestrator must expose an AgentRouter")
        if not callable(execute_task):
            raise TypeError("orchestrator must expose its canonical task execution entrypoint")

        class _HostWorkflow:
            def __init__(self, host: Any) -> None:
                self._host = host

            def execute(self, task_id: str):
                task = self._host.task_manager.get_task(task_id)
                self._host._execute_task(task)
                return self._host.task_manager.get_task(task_id)

        return cls(
            task_manager,
            agent_router=agent_router,
            workflow_factory=lambda _task_id: _HostWorkflow(orchestrator),
        )

    @staticmethod
    def _snapshot(task) -> MCPTaskSnapshot:
        return MCPTaskSnapshot(
            id=task.id,
            title=task.title,
            role=task.role,
            status=task.status,
            dependencies=tuple(task.dependencies),
            error=task.error,
            review_round=task.review_round,
            retry_attempt=task.retry_attempt,
            max_retries=task.max_retries,
            cancellation_requested=task.cancellation_requested,
        )

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks = self._task_manager.get_all_tasks()
        return [self._snapshot(task).as_dict() for task in tasks]

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
        result: list[dict[str, Any]] = []
        for role in sorted(agents):
            agent = agents[role]
            result.append({"role": role, "registered": agent is not None})
        return result

    def workflow_capabilities(self) -> dict[str, bool]:
        return {
            "task_read": True,
            "agent_read": self._agent_router is not None,
            "workflow_execute": self._workflow_factory is not None,
            "workflow_cancel": False,
        }

    def _execution_lock(self, task_id: str) -> Lock:
        with self._execution_locks_guard:
            lock = self._execution_locks.get(task_id)
            if lock is None:
                lock = Lock()
                self._execution_locks[task_id] = lock
            return lock

    def execute_task(self, task_id: str) -> dict[str, Any]:
        if self._workflow_factory is None:
            raise RuntimeError("MCP workflow execution is not configured")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        normalized_id = task_id.strip()
        task = self._task_manager.ensure_executable(normalized_id)
        if task.status != "ready":
            raise RuntimeError(f"Task {normalized_id} is already active with status {task.status}")
        lock = self._execution_lock(normalized_id)
        if not lock.acquire(blocking=False):
            raise RuntimeError(f"Task {normalized_id} is already being executed")
        try:
            task = self._task_manager.get_task(normalized_id)
            if task.status != "ready":
                raise RuntimeError(f"Task {normalized_id} is already active with status {task.status}")
            workflow = self._workflow_factory(normalized_id)
            execute = getattr(workflow, "execute", None)
            if not callable(execute):
                raise TypeError("workflow factory must return an object exposing execute(task_id)")
            task = execute(normalized_id)
            return self._snapshot(task).as_dict()
        finally:
            lock.release()
