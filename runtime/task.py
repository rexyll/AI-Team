from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    id: str
    title: str
    description: str
    role: str
    status: str = "pending"
    dependencies: list[str] = field(
        default_factory=list
    )
    result: dict[str, Any] = field(
        default_factory=dict
    )