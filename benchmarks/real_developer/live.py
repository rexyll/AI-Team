from __future__ import annotations

from typing import Callable

from runtime.agent_config import AgentConfig
from runtime.llm.provider import ProviderLLM
from runtime.task_manager import TaskManager

from .executor import DeveloperAgentExecutor


def build_live_executor_factory(
    *,
    provider_profile: str | None = None,
    model: str | None = None,
    config_factory: Callable[[int], AgentConfig | None] | None = None,
) -> Callable[[TaskManager, int], DeveloperAgentExecutor]:
    """Build an executor factory that uses real OpenAI-compatible providers.

    Provider clients are constructed lazily per Developer binding. The factory
    itself performs no network calls; a call occurs only when a task executes.
    """

    def factory(manager: TaskManager, developer_count: int) -> DeveloperAgentExecutor:
        return DeveloperAgentExecutor(
            manager,
            developer_count,
            llm_factory=lambda: ProviderLLM(
                provider_profile=provider_profile,
                model=model,
            ),
            config_factory=config_factory,
        )

    return factory
