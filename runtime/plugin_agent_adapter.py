from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.task import Task


class _RoutableAgent(Protocol):
    role: str

    def run(self, task: Task) -> AgentResult: ...


class PluginAgentInvocationAdapter:
    """Narrow plugin-facing Agent boundary backed by the host AgentRouter.

    The adapter binds one host-selected Agent role. Plugins cannot access the
    router, Agent instance, LLM, tool loop, or mutable runtime Task object.
    Developer tasks continue to use the existing deterministic pool routing.
    """

    def __init__(self, router: AgentRouter, *, role: str) -> None:
        if not isinstance(router, AgentRouter):
            raise TypeError("router must be an AgentRouter")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role must be a non-empty string")
        if not router.has_agent(role.strip()):
            raise ValueError(f"unknown agent role: {role}")
        self._router = router
        self._role = role.strip()

    @property
    def role(self) -> str:
        """Return the host-assigned Agent role."""
        return self._role

    def invoke(self, task: Task) -> AgentResult:
        """Run the host-selected Agent against an isolated Task copy."""
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        isolated_task = Task.from_dict(deepcopy(task.to_dict()))
        if self._role == "developer":
            agent = self._router.get_developer_for_task(isolated_task.id)
        else:
            agent = self._router.route(self._role)
        if not isinstance(getattr(agent, "role", None), str) or agent.role != self._role:
            raise RuntimeError("host Agent role does not match the adapter role")
        result = agent.run(isolated_task)
        if not isinstance(result, AgentResult):
            raise TypeError("host Agent must return AgentResult")
        return AgentResult.from_dict(deepcopy(result.to_dict()))
