from agents.planner import PlannerAgent
from runtime.agent_config import AgentConfig


def test_planner_agent_role():
    agent = PlannerAgent(
        AgentConfig(
            role="planner",
            model="default",
        )
    )

    assert agent.role == "planner"