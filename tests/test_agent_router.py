import pytest

from runtime.agent_router import AgentRouter
from agents.mock_agents import MockAgent


def test_register_agent():
    router = AgentRouter()

    agent = MockAgent("developer")

    router.register(agent)

    assert router.get_agent("developer") is agent


def test_register_agent_with_legacy_role_argument():
    router = AgentRouter()

    agent = MockAgent("developer")

    router.register("developer", agent)

    assert router.get_agent("developer") is agent


def test_register_duplicate_role_fails():
    router = AgentRouter()

    router.register(MockAgent("developer"))

    with pytest.raises(ValueError):
        router.register(MockAgent("developer"))


def test_register_role_mismatch_fails():
    router = AgentRouter()

    agent = MockAgent("reviewer")

    with pytest.raises(ValueError):
        router.register("developer", agent)


def test_register_non_base_agent_fails():
    router = AgentRouter()

    class InvalidAgent:
        @property
        def role(self):
            return "developer"

        def run(self, task):
            return {}

    with pytest.raises(TypeError):
        router.register(InvalidAgent())


def test_get_unknown_agent_returns_none():
    router = AgentRouter()

    assert router.get_agent("developer") is None


def test_has_agent():
    router = AgentRouter()

    router.register(MockAgent("developer"))

    assert router.has_agent("developer")
    assert not router.has_agent("reviewer")


def test_list_agents():
    router = AgentRouter()

    developer = MockAgent("developer")
    tester = MockAgent("tester")
    reviewer = MockAgent("reviewer")

    router.register(developer)
    router.register(tester)
    router.register(reviewer)

    agents = router.list_agents()

    assert agents["developer"] is developer
    assert agents["tester"] is tester
    assert agents["reviewer"] is reviewer


def test_route_returns_registered_agent():
    router = AgentRouter()

    developer = MockAgent("developer")

    router.register(developer)

    agent = router.route("developer")

    assert agent is developer


def test_route_unknown_role_fails():
    router = AgentRouter()

    with pytest.raises(KeyError):
        router.route("developer")