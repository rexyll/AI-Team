from collections.abc import Mapping

from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent

from config.model import (
    get_developer_count,
    resolve_developer_llm_spec,
    resolve_role_llm_spec,
)
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.llm.provider import ProviderLLM


AgentConfigMap = Mapping[str, AgentConfig]


def _default_agent_configs() -> dict[str, AgentConfig]:
    return {
        role: AgentConfig(role=role, model="")
        for role in ("architect", "developer", "tester", "reviewer", "planner")
    }


def create_agent_router(configs: AgentConfigMap | None = None) -> AgentRouter:
    default_configs = _default_agent_configs()

    if configs is None:
        effective_configs = default_configs
    else:
        required_core_roles = {"architect", "developer", "tester", "reviewer"}
        missing_roles = required_core_roles - set(configs.keys())
        if missing_roles:
            raise ValueError(
                "Missing agent configurations: " + ", ".join(sorted(missing_roles))
            )
        effective_configs = {**default_configs, **configs}

    supported_roles = {"architect", "developer", "tester", "reviewer", "planner"}
    for role in supported_roles:
        config = effective_configs.get(role)
        if config is None:
            raise ValueError(f"Missing agent configuration: {role}")
        if not isinstance(config, AgentConfig):
            raise TypeError(f"config for role '{role}' must be an AgentConfig")
        if config.role != role:
            raise ValueError(
                f"AgentConfig role mismatch: expected '{role}', got '{config.role}'"
            )

    router = AgentRouter()

    role_llms: dict[str, ProviderLLM] = {}
    for role in ("architect", "tester", "reviewer", "planner"):
        provider_name, model_id = resolve_role_llm_spec(role)
        role_llms[role] = ProviderLLM(
            model=model_id,
            provider_profile=provider_name,
        )

    router.register(
        "architect",
        ArchitectAgent(effective_configs["architect"], llm=role_llms["architect"]),
    )

    developer_count = get_developer_count()
    base_config = effective_configs["developer"]
    developer_agents: list[DeveloperAgent] = []

    for index in range(1, developer_count + 1):
        provider_name, model_id = resolve_developer_llm_spec(index)

        # Preserve the legacy explicit AgentConfig object when the caller
        # deliberately supplies a single Developer configuration. For the
        # environment-driven default path, or a multi-Developer pool, the
        # resolved model and stable developer identity are materialized into
        # each individual AgentConfig.
        if developer_count == 1 and configs is not None and "developer" in configs:
            developer_config = base_config
        else:
            developer_config = AgentConfig(
                role="developer",
                model=model_id,
                temperature=base_config.temperature,
                max_tokens=base_config.max_tokens,
                enabled=base_config.enabled,
                system_prompt=base_config.system_prompt,
                extra={
                    **base_config.extra,
                    "developer_id": f"developer-{index}",
                },
            )

        developer_agents.append(
            DeveloperAgent(
                developer_config,
                llm=ProviderLLM(
                    model=model_id,
                    provider_profile=provider_name,
                ),
            )
        )

    router.register_developer_pool(developer_agents)

    router.register(
        "tester",
        TesterAgent(effective_configs["tester"], llm=role_llms["tester"]),
    )
    router.register(
        "reviewer",
        ReviewerAgent(effective_configs["reviewer"], llm=role_llms["reviewer"]),
    )
    router.register(
        "planner",
        PlannerAgent(effective_configs["planner"], llm=role_llms["planner"]),
    )

    return router
