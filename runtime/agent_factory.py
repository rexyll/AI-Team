import os
from collections.abc import Mapping

from agents.analyst import RequirementAnalystAgent
from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.doc_writer import DocWriterAgent
from agents.planner import PlannerAgent
from agents.tester import TesterAgent

from config.model import get_developer_count, resolve_developer_llm_spec, resolve_role_llm_spec
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.artifact_store import FilesystemArtifactStore
from runtime.llm.provider import ProviderLLM
from runtime.reviewer_reliability import create_reviewer_with_fallback

AgentConfigMap = Mapping[str, AgentConfig]

DEFAULT_ARTIFACT_MIN_CHARS = 16384

PROJECT_ROLES = ("architect", "tester", "reviewer", "planner", "analyst", "doc_writer")


def _developer_artifact_archive():
    """Return (store, threshold) for large-output archiving, or (None, None).

    Enabled by default with a 16 KiB threshold; the env variable
    ``AI_TEAM_ARTIFACT_MIN_CHARS`` overrides the threshold and a value of 0
    disables archiving (execution history then keeps full outputs as before).
    """
    raw = os.getenv("AI_TEAM_ARTIFACT_MIN_CHARS", "").strip()
    if not raw:
        threshold = DEFAULT_ARTIFACT_MIN_CHARS
    else:
        try:
            threshold = int(raw)
        except ValueError as exc:
            raise ValueError("AI_TEAM_ARTIFACT_MIN_CHARS must be an integer") from exc
        if threshold < 0:
            raise ValueError("AI_TEAM_ARTIFACT_MIN_CHARS must be >= 0")
    if threshold == 0:
        return None, None
    from security.workspace import PROJECT_ROOT

    return FilesystemArtifactStore(PROJECT_ROOT / "artifacts"), threshold


def _default_agent_configs() -> dict[str, AgentConfig]:
    return {
        role: AgentConfig(role=role, model="")
        for role in ("architect", "developer", "tester", "reviewer", "planner", "analyst", "doc_writer")
    }


def create_agent_router(configs: AgentConfigMap | None = None) -> AgentRouter:
    default_configs = _default_agent_configs()
    if configs is None:
        effective_configs = default_configs
    else:
        required_core_roles = {"architect", "developer", "tester", "reviewer"}
        missing_roles = required_core_roles - set(configs.keys())
        if missing_roles:
            raise ValueError("Missing agent configurations: " + ", ".join(sorted(missing_roles)))
        effective_configs = {**default_configs, **configs}

    supported_roles = {"architect", "developer", "tester", "reviewer", "planner", "analyst", "doc_writer"}
    for role in supported_roles:
        config = effective_configs.get(role)
        if config is None:
            raise ValueError(f"Missing agent configuration: {role}")
        if not isinstance(config, AgentConfig):
            raise TypeError(f"config for role '{role}' must be an AgentConfig")
        if config.role != role:
            raise ValueError(f"AgentConfig role mismatch: expected '{role}', got '{config.role}'")

    router = AgentRouter()
    role_llms: dict[str, ProviderLLM] = {}
    for role in PROJECT_ROLES:
        provider_name, model_id = resolve_role_llm_spec(role)
        role_llms[role] = ProviderLLM(model=model_id, provider_profile=provider_name)

    router.register("analyst", RequirementAnalystAgent(effective_configs["analyst"], llm=role_llms["analyst"]))
    router.register("architect", ArchitectAgent(effective_configs["architect"], llm=role_llms["architect"]))

    developer_count = 1 if configs is not None else get_developer_count()
    base_config = effective_configs["developer"]
    developer_agents: list[DeveloperAgent] = []
    artifact_store, artifact_min_chars = _developer_artifact_archive()

    for index in range(1, developer_count + 1):
        provider_name, model_id = resolve_developer_llm_spec(index)
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
                extra={**base_config.extra, "developer_id": f"developer-{index}"},
            )
        developer_agents.append(
            DeveloperAgent(
                developer_config,
                llm=ProviderLLM(model=model_id, provider_profile=provider_name),
                artifact_store=artifact_store,
                artifact_min_chars=artifact_min_chars,
            )
        )

    router.register_developer_pool(developer_agents)
    router.register("tester", TesterAgent(effective_configs["tester"], llm=role_llms["tester"]))
    router.register(
        "reviewer",
        create_reviewer_with_fallback(effective_configs["reviewer"], role_llms["reviewer"]),
    )
    router.register("planner", PlannerAgent(effective_configs["planner"], llm=role_llms["planner"]))
    router.register("doc_writer", DocWriterAgent(effective_configs["doc_writer"], llm=role_llms["doc_writer"]))
    return router
