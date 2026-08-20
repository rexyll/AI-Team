from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    """
    Runtime configuration for one AI Team agent.
    """

    role: str

    model: str

    temperature: float = 0.2

    max_tokens: int = 4096

    enabled: bool = True

    system_prompt: str = ""

    extra: dict[str, Any] = field(default_factory=dict)