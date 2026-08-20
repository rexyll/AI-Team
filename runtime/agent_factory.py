from collections.abc import Mapping

from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent

from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter


AgentConfigMap = Mapping[str, AgentConfig]


def _default_agent_configs() -> dict[str, AgentConfig]:
    return {
        "architect": AgentConfig(
            role="architect",
            model="default",
        ),
        "developer": AgentConfig(
            role="developer",
            model="default",
        ),
        "tester": AgentConfig(
            role="tester",
            model="default",
        ),
        "reviewer": AgentConfig(
            role="reviewer",
            model="default",
        ),
    }


def create_agent_router(
    configs: AgentConfigMap | None = None,
) -> AgentRouter:
    """
    Create and configure the AI Team AgentRouter.

    When configs is omitted, default configurations are used.

    Args:
        configs:
            Mapping from agent role to AgentConfig.

    Returns:
        Configured AgentRouter.
    """

    if configs is None:
        configs = _default_agent_configs()

    required_roles = {
        "architect",
        "developer",
        "tester",
        "reviewer",
    }

    missing_roles = required_roles - set(configs.keys())

    if missing_roles:
        raise ValueError(
            "Missing agent configurations: "
            + ", ".join(sorted(missing_roles))
        )

    for role in required_roles:
        config = configs[role]

        if not isinstance(config, AgentConfig):
            raise TypeError(
                f"config for role '{role}' "
                "must be an AgentConfig"
            )

        if config.role != role:
            raise ValueError(
                f"AgentConfig role mismatch: "
                f"expected '{role}', got '{config.role}'"
            )

    router = AgentRouter()

    router.register(
        "architect",
        ArchitectAgent(configs["architect"]),
    )

    router.register(
        "developer",
        DeveloperAgent(configs["developer"]),
    )

    router.register(
        "tester",
        TesterAgent(configs["tester"]),
    )

    router.register(
        "reviewer",
        ReviewerAgent(configs["reviewer"]),
    )

    return router