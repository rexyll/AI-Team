from abc import ABC, abstractmethod

from runtime.agent_config import AgentConfig
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_builder import ContextBuilder
from runtime.task import Task


class BaseAgent(ABC):

    def __init__(self, config: AgentConfig | None = None):
        self.config = config

    @property
    @abstractmethod
    def role(self) -> str:
        pass

    def build_context(
        self,
        task: Task,
        *,
        all_tasks: dict[str, Task] | None = None,
    ) -> AgentContext:
        """
        Build the canonical AgentContext used by this Agent.

        This is the compatibility bridge for the Phase 3 AgentContext
        migration. Existing workflow code can continue passing Task to
        ``run()``, while Agents that have migrated to AgentContext can use
        this helper to obtain an isolated execution snapshot.
        """
        return ContextBuilder(
            all_tasks=all_tasks,
        ).build_agent_context(
            task,
            role=self.role,
        )

    @abstractmethod
    def run(self, task: Task) -> AgentResult:
        """
        Execute one AI Team task.

        All agents must receive a runtime.task.Task object and return an
        AgentResult. During Phase 3, individual Agents will progressively
        migrate their internal execution logic to AgentContext.
        """
        pass
