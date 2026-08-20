from collections.abc import Mapping

from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent

from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter


AgentConfigMap = Mapping[str, AgentConfig]


def _default_agent_configs() -> dict[str, AgentConfig]:
    """
    Return the default configuration for all supported agents.
    """
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
        "planner": AgentConfig(
            role="planner",
            model="default",
        ),
    }


def create_agent_router(
    configs: AgentConfigMap | None = None,
) -> AgentRouter:
    """
    Create and configure the AI Team AgentRouter.

    Behavior:

    1. When ``configs`` is None, all default agent configurations
       are used.

    2. When custom ``configs`` are provided, the four original
       core agents must be explicitly configured:

           architect
           developer
           tester
           reviewer

       The planner configuration is optional and will fall back
       to the default planner configuration when omitted.

    Args:
        configs:
            Mapping from agent role to AgentConfig.

    Returns:
        A fully configured AgentRouter.

    Raises:
        ValueError:
            If one or more required core agent configurations
            are missing.

        TypeError:
            If a configuration value is not an AgentConfig.

        ValueError:
            If an AgentConfig.role does not match its mapping key.
    """

    default_configs = _default_agent_configs()

    # ------------------------------------------------------------------
    # No custom configuration:
    #
    # Use the complete default configuration.
    # ------------------------------------------------------------------
    if configs is None:
        effective_configs = default_configs

    # ------------------------------------------------------------------
    # Custom configuration:
    #
    # The four original core agents must be explicitly provided.
    # Planner is optional for backward compatibility and will use
    # the default configuration when omitted.
    # ------------------------------------------------------------------
    else:
        required_core_roles = {
            "architect",
            "developer",
            "tester",
            "reviewer",
        }

        missing_roles = required_core_roles - set(configs.keys())

        if missing_roles:
            raise ValueError(
                "Missing agent configurations: "
                + ", ".join(sorted(missing_roles))
            )

        effective_configs = {
            **default_configs,
            **configs,
        }

    # ------------------------------------------------------------------
    # Validate every configuration that will actually be used.
    # ------------------------------------------------------------------
    supported_roles = {
        "architect",
        "developer",
        "tester",
        "reviewer",
        "planner",
    }

    for role in supported_roles:
        config = effective_configs.get(role)

        if config is None:
            raise ValueError(
                f"Missing agent configuration: {role}"
            )

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

    # ------------------------------------------------------------------
    # Create router.
    # ------------------------------------------------------------------
    router = AgentRouter()

    # ------------------------------------------------------------------
    # Register agents.
    # ------------------------------------------------------------------
    router.register(
        "architect",
        ArchitectAgent(effective_configs["architect"]),
    )

    router.register(
        "developer",
        DeveloperAgent(effective_configs["developer"]),
    )

    router.register(
        "tester",
        TesterAgent(effective_configs["tester"]),
    )

    router.register(
        "reviewer",
        ReviewerAgent(effective_configs["reviewer"]),
    )

    router.register(
        "planner",
        PlannerAgent(effective_configs["planner"]),
    )

    return router