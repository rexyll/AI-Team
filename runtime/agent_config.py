from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:

    role: str

    model: str

    temperature: float = 0.2

    max_tokens: int = 4096