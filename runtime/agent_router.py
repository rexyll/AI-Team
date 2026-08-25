import hashlib

from agents.base import BaseAgent


class AgentRouter:
    """Registry for singleton role agents plus a configurable Developer pool."""

    def __init__(self):
        self.agents: dict[str, object] = {}
        self.developers: list[object] = []

    def register(
        self,
        agent_or_role,
        agent: object | None = None,
    ) -> None:
        if agent is None:
            agent = agent_or_role
            if not isinstance(agent, BaseAgent):
                raise TypeError("agent must be an instance of BaseAgent")
            role = agent.role
        else:
            role = agent_or_role
            if not isinstance(role, str) or not role.strip():
                raise ValueError("Agent role must be a non-empty string")
            role = role.strip()
            if hasattr(agent, "role"):
                agent_role = getattr(agent, "role")
                if not isinstance(agent_role, str) or not agent_role.strip():
                    raise ValueError("agent.role must be a non-empty string")
                if role != agent_role.strip():
                    raise ValueError(
                        f"Agent role mismatch: registered role '{role}' "
                        f"does not match agent.role '{agent_role}'"
                    )

        if not isinstance(role, str) or not role.strip():
            raise ValueError("Agent role must be a non-empty string")
        role = role.strip()

        if role in self.agents:
            raise ValueError(f"Agent role already registered: {role}")

        self.agents[role] = agent
        if role == "developer":
            self.developers = [agent]

    def register_developer_pool(self, agents: list[object]) -> None:
        """Register multiple Developer agents sharing the same logical role."""
        if not isinstance(agents, list) or not agents:
            raise ValueError("developer pool must contain at least one agent")
        if any(not isinstance(agent, BaseAgent) for agent in agents):
            raise TypeError("all developer pool members must be BaseAgent instances")
        if any(agent.role != "developer" for agent in agents):
            raise ValueError("all developer pool members must have role='developer'")
        if "developer" in self.agents:
            raise ValueError("developer role is already registered")
        self.developers = list(agents)
        self.agents["developer"] = self.developers[0]

    def get_agent(self, role: str) -> object | None:
        return self.agents.get(role)

    def get_developers(self) -> list[object]:
        """Return a shallow copy of the configured Developer pool."""
        return list(self.developers)

    def get_developer_for_task(self, task_id: str) -> object:
        """Select a stable Developer from the pool using SHA-256."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not self.developers:
            raise KeyError("No developer agents are registered")
        digest = hashlib.sha256(task_id.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % len(self.developers)
        return self.developers[index]

    def route(self, role: str) -> object:
        try:
            return self.agents[role]
        except KeyError:
            raise KeyError(f"No agent registered for role: {role}") from None

    def has_agent(self, role: str) -> bool:
        return role in self.agents

    def list_agents(self) -> dict[str, object]:
        return self.agents.copy()
