from runtime.agent_config import AgentConfig


class AgentRegistry:

    def __init__(self):
        self._configs: dict[str, AgentConfig] = {}

    def register(self, config: AgentConfig) -> None:
        if not isinstance(config, AgentConfig):
            raise TypeError(
                "config must be an instance of AgentConfig"
            )

        if not config.role.strip():
            raise ValueError(
                "Agent role must be a non-empty string"
            )

        if config.role in self._configs:
            raise ValueError(
                f"Agent config already registered: {config.role}"
            )

        self._configs[config.role] = config

    def get(self, role: str) -> AgentConfig | None:
        return self._configs.get(role)

    def list_configs(self) -> dict[str, AgentConfig]:
        return dict(self._configs)

    def has(self, role: str) -> bool:
        return role in self._configs