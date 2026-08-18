class AgentRouter:

    def __init__(self):
        self.agents = {}

    def register(self, role: str, agent) -> None:
        if role in self.agents:
            raise ValueError(
                f"Agent role already registered: {role}"
            )

        self.agents[role] = agent

    def get_agent(self, role: str):
        if role not in self.agents:
            raise ValueError(
                f"No agent registered for role: {role}"
            )

        return self.agents[role]

    def has_agent(self, role: str) -> bool:
        return role in self.agents