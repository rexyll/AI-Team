from agents.base import BaseAgent


class AgentRouter:

    def __init__(self):
        self.agents: dict[str, BaseAgent] = {}

    def register(
        self,
        agent: BaseAgent,
    ) -> None:

        if not isinstance(agent, BaseAgent):
            raise TypeError(
                "agent must be an instance of BaseAgent"
            )

        role = agent.role

        if role in self.agents:
            raise ValueError(
                f"Agent role already registered: {role}"
            )

        self.agents[role] = agent

    def get_agent(
        self,
        role: str,
    ) -> BaseAgent:

        if role not in self.agents:
            raise ValueError(
                f"No agent registered for role: {role}"
            )

        return self.agents[role]

    def has_agent(
        self,
        role: str,
    ) -> bool:

        return role in self.agents