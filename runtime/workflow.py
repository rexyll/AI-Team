from __future__ import annotations

from typing import Callable

from runtime.agent_router import AgentRouter
from runtime.result_normalizer import normalize_agent_result
from runtime.task import Task
from runtime.task_manager import TaskManager


MAX_REVIEW_ROUNDS = 3


class TaskWorkflow:
    def __init__(
        self,
        task_manager: TaskManager,
        developer,
        reviewer,
        agent_router: AgentRouter,
        max_review_rounds: int = MAX_REVIEW_ROUNDS,
        tester=None,
        state_change_hook: Callable[[TaskManager], None] | None = None,
    ):
        if max_review_rounds <= 0:
            raise ValueError("max_review_rounds must be greater than 0")
        self.task_manager = task_manager
        self._developer = developer
        self._reviewer = reviewer
        self._tester = tester
        self.agent_router = agent_router
        self.max_review_rounds = max_review_rounds
        self.state_change_hook = state_change_hook
        self._validate_explicit_agent("developer", developer)
        self._validate_explicit_agent("tester", tester)
        self._validate_explicit_agent("reviewer", reviewer)

    def _validate_explicit_agent(self, role: str, agent) -> None:
        if agent is None:
            return
        get_agent = getattr(self.agent_router, "get_agent", None)
        if not callable(get_agent):
            return
        registered = get_agent(role)
        if registered is None:
            raise ValueError(f"No agent registered for role: {role}")
        if agent is not registered:
            raise ValueError(
                f"TaskWorkflow {role} agent must be the instance registered by the router"
            )

    def _agent(self, role: str, fallback=None):
        get_agent = getattr(self.agent_router, "get_agent", None)
        if callable(get_agent):
            agent = get_agent(role)
            if agent is not None:
                return agent
        return fallback

    @property
    def developer(self):
        return self._agent("developer", self._developer)

    @property
    def reviewer(self):
        return self._agent("reviewer", self._reviewer)

    @property
    def tester(self):
        return self._agent("tester", self._tester)

    def _notify_state_change(self) -> None:
        if self.state_change_hook is not None:
            self.state_change_hook(self.task_manager)

    def run(self) -> None:
        while True:
            task = self.task_manager.next_ready_task()
            if task is None:
                break
            self.execute_task(task)

    def execute_task(self, task: Task) -> None:
        self.task_manager.mark_running(task.id)
        self._notify_state_change()
        try:
            developer = self.developer
            result = normalize_agent_result(
                developer.run(task),
                expected_agent="developer",
                expected_task_id=task.id,
            )
            if result.status != "completed":
                self.task_manager.mark_failed(task.id, result.message)
                self._notify_state_change()
                return
            self.task_manager.mark_completed(task.id, result.to_dict())
            self._notify_state_change()
        except Exception as exc:
            self.task_manager.mark_failed(task.id, str(exc))
            self._notify_state_change()
