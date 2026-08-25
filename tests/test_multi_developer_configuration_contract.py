import pytest

from agents.developer import DeveloperAgent
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter
from runtime.agent_factory import create_agent_router


def _developer(name: str, model: str) -> DeveloperAgent:
    return DeveloperAgent(
        AgentConfig(
            role="developer",
            model=model,
            extra={"developer_id": name},
        )
    )


def test_router_registers_multiple_developers():
    first = _developer("developer-1", "model-a")
    second = _developer("developer-2", "model-b")
    third = _developer("developer-3", "model-c")

    router = AgentRouter()
    router.register_developer_pool([first, second, third])

    assert router.get_agent("developer") is first
    assert router.get_developers() == [first, second, third]
    assert router.get_developer_for_task("TASK-001") in {first, second, third}
    assert router.get_developer_for_task("TASK-002") in {first, second, third}


def test_task_assignment_is_stable_for_same_task_id():
    developers = [
        _developer("developer-1", "model-a"),
        _developer("developer-2", "model-b"),
        _developer("developer-3", "model-c"),
    ]
    router = AgentRouter()
    router.register_developer_pool(developers)

    assigned = router.get_developer_for_task("TASK-017")
    assert router.get_developer_for_task("TASK-017") is assigned


def test_empty_developer_pool_is_rejected():
    router = AgentRouter()
    with pytest.raises(ValueError):
        router.register_developer_pool([])


def test_factory_materializes_individual_developer_models(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "alpha,beta")
    monkeypatch.setenv("DEFAULT_PROVIDER", "alpha")
    monkeypatch.setenv("DEFAULT_MODEL", "alpha-default")
    monkeypatch.setenv("ALPHA_API_KEY", "alpha-key")
    monkeypatch.setenv("ALPHA_BASE_URL", "https://alpha.example/v1")
    monkeypatch.setenv("ALPHA_MODEL", "alpha-model")
    monkeypatch.setenv("BETA_API_KEY", "beta-key")
    monkeypatch.setenv("BETA_BASE_URL", "https://beta.example/v1")
    monkeypatch.setenv("BETA_MODEL", "beta-model")
    monkeypatch.setenv("DEVELOPER_COUNT", "3")
    monkeypatch.setenv("DEVELOPER_1_PROVIDER", "alpha")
    monkeypatch.setenv("DEVELOPER_1_MODEL", "dev-alpha")
    monkeypatch.setenv("DEVELOPER_2_PROVIDER", "beta")
    monkeypatch.setenv("DEVELOPER_2_MODEL", "dev-beta")
    monkeypatch.setenv("DEVELOPER_3_PROVIDER", "alpha")
    monkeypatch.setenv("DEVELOPER_3_MODEL", "dev-alpha-fast")

    router = create_agent_router()
    developers = router.get_developers()

    assert len(developers) == 3
    assert [agent.config.model for agent in developers] == [
        "dev-alpha",
        "dev-beta",
        "dev-alpha-fast",
    ]
    assert [agent.config.extra["developer_id"] for agent in developers] == [
        "developer-1",
        "developer-2",
        "developer-3",
    ]
