from dataclasses import dataclass, field
from typing import Any


VALID_RESULT_STATUSES = {
    "completed",
    "failed",
    "approved",
    "revision",
    "passed",
    "blocked",
}


@dataclass
class AgentResult:
    """
    Unified result contract returned by an Agent.

    The contract deliberately keeps status as a string so that it remains
    compatible with the existing Developer / Reviewer / Tester protocols.
    """

    status: str
    agent: str
    task_id: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("AgentResult status must be a non-empty string")

        if not isinstance(self.agent, str) or not self.agent.strip():
            raise ValueError("AgentResult agent must be a non-empty string")

        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("AgentResult task_id must be a non-empty string")

        if not isinstance(self.message, str):
            raise ValueError("AgentResult message must be a string")

        if not isinstance(self.data, dict):
            raise ValueError("AgentResult data must be a dictionary")

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to the legacy dictionary format."""
        return {
            "status": self.status,
            "agent": self.agent,
            "task_id": self.task_id,
            "message": self.message,
            "data": self.data,
        }
        
    def __getitem__(self, key: str) -> Any:
        if key == "status":
            return self.status

        if key == "agent":
            return self.agent

        if key == "task_id":
            return self.task_id

        if key == "message":
            return self.message

        if key == "data":
            return self.data

        raise KeyError(key)
    
    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    @classmethod
    def from_dict(cls, result: dict[str, Any]) -> "AgentResult":
        """Create an AgentResult from the existing dictionary protocol."""
        if not isinstance(result, dict):
            raise ValueError("AgentResult input must be a dictionary")

        required_fields = (
            "status",
            "agent",
            "task_id",
        )

        missing = [
            field
            for field in required_fields
            if field not in result
        ]

        if missing:
            raise ValueError(
                "AgentResult missing required fields: "
                + ", ".join(missing)
            )

        return cls(
            status=result["status"],
            agent=result["agent"],
            task_id=result["task_id"],
            message=result.get("message", ""),
            data=result.get("data", {}),
        )
        
    