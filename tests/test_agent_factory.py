import pytest

from runtime.agent_config import AgentConfig
from runtime.agent_factory import create_agent_router
from runtime.reviewer_reliability import ResilientReviewerAgent


def test_agent_factory_registers_all_agents():
    router = create_agent_router()

    assert router.get_agent("architect") is not None
    assert router.get_agent("developer") is not None
    assert router.get_agent("tester") is not None
    assert router.get_agent("reviewer") is not None


def test_agent_factory_registers_reviewer_reliability_wrapper():
    router = create_agent_router()
    reviewer = router.get_agent("reviewer")

    assert isinstance(reviewer, ResilientReviewerAgent)
    assert reviewer.role == "reviewer"
    assert reviewer.primary.role == "reviewer"
    assert reviewer.fallback is None


def test_agent_factory_uses_custom_configs():
    configs = {
        "architect": AgentConfig(role="architect", model="architect-model", temperature=0.1),
        "developer": AgentConfig(role="developer", model="developer-model", temperature=0.2),
        "tester": AgentConfig(role="tester", model="tester-model", temperature=0.0),
        "reviewer": AgentConfig(role="reviewer", model="reviewer-model", temperature=0.1),
    }

    router = create_agent_router(configs)

    assert router.get_agent("architect").config == configs["architect"]
    assert router.get_agent("developer").config == configs["developer"]
    assert router.get_agent("tester").config == configs["tester"]
    assert router.get_agent("reviewer").config == configs["reviewer"]


def test_agent_factory_missing_config_fails():
    configs = {
        "architect": AgentConfig(role="architect", model="architect-model"),
        "developer": AgentConfig(role="developer", model="developer-model"),
    }

    with pytest.raises(ValueError):
        create_agent_router(configs)


def test_agent_factory_config_role_mismatch_fails():
    configs = {
        "architect": AgentConfig(role="developer", model="architect-model"),
        "developer": AgentConfig(role="developer", model="developer-model"),
        "tester": AgentConfig(role="tester", model="tester-model"),
        "reviewer": AgentConfig(role="reviewer", model="reviewer-model"),
    }

    with pytest.raises(ValueError):
        create_agent_router(configs)
