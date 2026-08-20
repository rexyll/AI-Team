from agents.base import BaseAgent


class AgentRouter:

    def __init__(self):
        self.agents: dict[str, BaseAgent] = {}

    def register(
        self,
        agent_or_role,
        agent: BaseAgent | None = None,
    ) -> None:
        """
        Register an Agent.

        Preferred API:

            router.register(agent)

        Legacy API:

            router.register("developer", agent)

        The legacy form is kept for backward compatibility.
        """

        if agent is None:
            # New API:
            # router.register(agent)

            agent = agent_or_role

            if not isinstance(agent, BaseAgent):
                raise TypeError(
                    "agent must be an instance of BaseAgent"
                )

            role = agent.role

        else:
            # Legacy API:
            # router.register("developer", agent)

            role = agent_or_role

            if not isinstance(role, str) or not role.strip():
                raise ValueError(
                    "Agent role must be a non-empty string"
                )

            if not isinstance(agent, BaseAgent):
                raise TypeError(
                    "agent must be an instance of BaseAgent"
                )

            if agent.role != role:
                raise ValueError(
                    f"Agent role mismatch: "
                    f"registered role '{role}' "
                    f"does not match agent role '{agent.role}'"
                )

        if role in self.agents:
            raise ValueError(
                f"Agent role already registered: {role}"
            )

        self.agents[role] = agent

    def get_agent(
        self,
        role: str,
    ) -> BaseAgent | None:
        """
        Return the registered agent for a role.

        Returns None when the role has not been registered.

        This method keeps the original AgentRouter contract.
        """

        return self.agents.get(role)

    def route(
        self,
        role: str,
    ) -> BaseAgent:
        """
        Route a role to its registered Agent.

        Raises:
            KeyError:
                If no agent is registered for the role.
        """

        try:
            return self.agents[role]
        except KeyError:
            raise KeyError(
                f"No agent registered for role: {role}"
            ) from None

    def has_agent(
        self,
        role: str,
    ) -> bool:
        """
        Return True when an agent is registered for the role.
        """

        return role in self.agents

    def list_agents(
        self,
    ) -> dict[str, BaseAgent]:
        """
        Return all registered agents.

        A shallow copy is returned so callers cannot directly
        modify the router's internal registry.
        """

        return self.agents.copy()