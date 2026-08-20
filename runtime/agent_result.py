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

    Compatibility rules:

    1. ``agent`` and ``task_id`` may be omitted when constructing an
       AgentResult directly. This is required by the runtime contract
       layer, which may validate a partially populated result object.

    2. ``from_dict()`` remains strict and requires:
           status
           agent
           task_id

       This prevents malformed external/legacy dictionaries from silently
       becoming valid AgentResult objects.

    3. Legacy Agent-specific payload fields are normalized into ``data``.

       For example:

           {
               "status": "architect_completed",
               "agent": "architect",
               "task_id": "TASK-001",
               "architecture": "SQLite architecture",
           }

       becomes:

           AgentResult(
               status="completed",
               agent="architect",
               task_id="TASK-001",
               data={
                   "architecture": "SQLite architecture"
               }
           )

    4. Legacy payload fields remain directly accessible through
       ``result[key]`` and ``result.get(key)``.
    """

    status: str
    agent: str | None = None
    task_id: str | None = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError(
                "AgentResult status must be a non-empty string"
            )

        if self.agent is not None:
            if not isinstance(self.agent, str) or not self.agent.strip():
                raise ValueError(
                    "AgentResult agent must be a non-empty string"
                )

        if self.task_id is not None:
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
        """
        Dictionary-style access to canonical fields and legacy payload fields.

        Canonical:

            result["status"]
            result["agent"]
            result["task_id"]
            result["message"]
            result["data"]

        Legacy payload:

            result["architecture"]
            result["implementation"]
            result["risk"]

        Legacy fields are resolved from ``self.data``.
        """
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

        if key in self.data:
            return self.data[key]

        raise KeyError(key)

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Dictionary-style ``get()`` with support for legacy payload fields.
        """
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

        ``from_dict()`` intentionally requires the three core fields:

            status
            agent
            task_id

        This is stricter than direct AgentResult construction because
        dictionary input normally represents an external/runtime boundary.

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

        # Copy the dictionary so the caller's original object is never
        # modified by normalization.
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
                    # Canonical data wins if the same key exists.
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
                # Canonical ``data`` wins over legacy top-level fields.
                data.setdefault(key, value)

        return cls(
            status=result["status"],
            agent=result["agent"],
            task_id=result["task_id"],
            message=result.get("message", ""),
            data=data,
        )

    @classmethod
    def from_any(
        cls,
        result: "AgentResult | dict[str, Any]",
        *,
        agent: str | None = None,
        task_id: str | None = None,
    ) -> "AgentResult":
        """
        Normalize either an AgentResult or a dictionary.

        When dictionary input is supplied, optional ``agent`` and
        ``task_id`` arguments can fill missing fields before passing the
        payload through the strict ``from_dict()`` contract.

        Example:

            AgentResult.from_any(
                {"status": "completed"},
                agent="developer",
                task_id="TASK-001",
            )
        """
        if isinstance(result, cls):
            return result

        if not isinstance(result, dict):
            raise TypeError(
                "Agent result must be an AgentResult or dict"
            )

        payload = dict(result)

        if agent is not None:
            payload.setdefault("agent", agent)

        if task_id is not None:
            payload.setdefault("task_id", task_id)

        return cls.from_dict(payload)

    @property
    def succeeded(self) -> bool:
        """
        Whether the result represents a successful outcome.
        """
        return self.status in {
            "completed",
            "approved",
            "passed",
        }

    @property
    def failed(self) -> bool:
        """
        Whether the result represents a failed outcome.
        """
        return self.status == "failed"

    @property
    def requires_revision(self) -> bool:
        """
        Whether the result requires another development/review round.
        """
        return self.status == "revision"
