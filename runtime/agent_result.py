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


LEGACY_STATUS_MAPPING = {
    "architect_completed": "completed",
    "developer_completed": "completed",
    "tester_passed": "passed",
    "tester_failed": "failed",
    "reviewer_approved": "approved",
    "reviewer_revision": "revision",
}


def normalize_result_status(status: str) -> str:
    """
    Normalize legacy Agent status values into the canonical status set.

    Unknown statuses are preserved so that AgentResult remains forward
    compatible with future Agent-specific states.
    """
    if not isinstance(status, str):
        raise ValueError(
            "AgentResult status must be a non-empty string"
        )

    status = status.strip()

    if not status:
        raise ValueError(
            "AgentResult status must be a non-empty string"
        )

    return LEGACY_STATUS_MAPPING.get(status, status)


@dataclass
class AgentResult:
    """
    Unified result contract returned by an Agent.

    Canonical structure:

        status
        agent
        task_id
        message
        data

    Legacy Agent-specific payload fields are normalized into ``data``.
    """

    status: str
    agent: str
    task_id: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError(
                "AgentResult status must be a non-empty string"
            )

        if not isinstance(self.agent, str) or not self.agent.strip():
            raise ValueError(
                "AgentResult agent must be a non-empty string"
            )

        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError(
                "AgentResult task_id must be a non-empty string"
            )

        if not isinstance(self.message, str):
            raise ValueError(
                "AgentResult message must be a string"
            )

        if not isinstance(self.data, dict):
            raise ValueError(
                "AgentResult data must be a dictionary"
            )

        self.status = normalize_result_status(self.status)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the result to the canonical dictionary format.
        """
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

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    @classmethod
    def from_dict(
        cls,
        result: dict[str, Any],
    ) -> "AgentResult":
        """
        Create an AgentResult from either:

        1. Canonical AgentResult dictionaries.
        2. Legacy Agent dictionaries.

        Legacy Agent-specific payload fields are normalized into ``data``.
        """
        if not isinstance(result, dict):
            raise ValueError(
                "AgentResult input must be a dictionary"
            )

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

        # ------------------------------------------------------------
        # Canonical business payload
        # ------------------------------------------------------------
        data = result.get("data", {})

        if not isinstance(data, dict):
            raise ValueError(
                "AgentResult data must be a dictionary"
            )

        data = dict(data)

        # ------------------------------------------------------------
        # Legacy business payload
        #
        # Older agents may return:
        #
        # {
        #     "status": "completed",
        #     "agent": "developer",
        #     "task_id": "TASK-002",
        #     "result": {
        #         "implementation": "..."
        #     }
        # }
        #
        # Normalize it into:
        #
        # {
        #     "implementation": "..."
        # }
        # ------------------------------------------------------------
        legacy_result = result.get("result")

        if legacy_result is not None:
            if isinstance(legacy_result, dict):
                for key, value in legacy_result.items():
                    data.setdefault(key, value)
            else:
                data.setdefault(
                    "result",
                    legacy_result,
                )

        # ------------------------------------------------------------
        # Preserve other legacy Agent-specific fields.
        # ------------------------------------------------------------
        reserved_fields = {
            "status",
            "agent",
            "task_id",
            "message",
            "data",
            "result",
        }

        for key, value in result.items():
            if key not in reserved_fields:
                data.setdefault(key, value)

        return cls(
            status=result["status"],
            agent=result["agent"],
            task_id=result["task_id"],
            message=result.get("message", ""),
            data=data,
        )