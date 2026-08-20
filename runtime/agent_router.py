from agents.base import BaseAgent


class AgentRouter:

    def __init__(self):
        self.agents: dict[str, object] = {}

    def register(
        self,
        agent_or_role,
        agent: object | None = None,
    ) -> None:
        """
        Register an Agent.

        Preferred API:
            router.register(agent)

        Legacy API:
            router.register("developer", agent)

        Rules:

        1. New API requires a real BaseAgent.
        2. Legacy API supports Mock/Fake agents.
        3. If a legacy agent exposes ``role``, the explicit role must
        match ``agent.role``.
        4. A role can only be registered once.
        """

        if agent is None:
            # =========================================================
            # New API
            #
            #     router.register(agent)
            #
            # New API requires a real BaseAgent.
            # =========================================================

            agent = agent_or_role

            if not isinstance(agent, BaseAgent):
                raise TypeError(
                    "agent must be an instance of BaseAgent"
                )

            role = agent.role

        else:
            # =========================================================
            # Legacy API
            #
            #     router.register("developer", agent)
            #
            # Existing workflow tests use lightweight Mock/Fake agents.
            # Some of them do not define a role attribute, so we must
            # preserve duck-typed compatibility.
            # =========================================================

            role = agent_or_role

            if not isinstance(role, str) or not role.strip():
                raise ValueError(
                    "Agent role must be a non-empty string"
                )

            role = role.strip()

            # ---------------------------------------------------------
            # If the legacy agent exposes role, validate consistency.
            #
            # Example:
            #
            #     router.register(
            #         "developer",
            #         MockAgent("reviewer"),
            #     )
            #
            # must fail.
            #
            # But lightweight test doubles such as:
            #
            #     FailingDeveloper()
            #
            # may not have role at all. Those remain supported.
            # ---------------------------------------------------------

            if hasattr(agent, "role"):
                agent_role = getattr(agent, "role")

                if not isinstance(agent_role, str) or not agent_role.strip():
                    raise ValueError(
                        "agent.role must be a non-empty string"
                    )

                agent_role = agent_role.strip()

                if role != agent_role:
                    raise ValueError(
                        f"Agent role mismatch: "
                        f"registered role '{role}' does not match "
                        f"agent.role '{agent_role}'"
                    )

        # =============================================================
        # Common role validation
        # =============================================================

        if not isinstance(role, str) or not role.strip():
            raise ValueError(
                "Agent role must be a non-empty string"
            )

        role = role.strip()

        # =============================================================
        # Duplicate role protection
        # =============================================================

        if role in self.agents:
            raise ValueError(
                f"Agent role already registered: {role}"
            )

        # =============================================================
        # Register
        # =============================================================

        self.agents[role] = agent

    def get_agent(
        self,
        role: str,
    ) -> object | None:
        """
        Return the registered agent for a role.

        Returns None when the role has not been registered.
        """

        return self.agents.get(role)

    def route(
        self,
        role: str,
    ) -> object:
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
    ) -> dict[str, object]:
        """
        Return all registered agents.

        A shallow copy is returned so callers cannot directly
        modify the router's internal registry.
        """

        return self.agents.copy()