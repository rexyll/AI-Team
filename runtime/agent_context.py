from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """
    Immutable-in-practice execution snapshot passed to an Agent.

    AgentContext intentionally separates Agent execution input from the
    runtime Task object.

    The context contains only data required by an Agent during execution.
    Mutable nested values are deep-copied so later Task mutations cannot
    silently modify an already-built AgentContext.
    """

    task_id: str
    task_title: str
    task_description: str

    role: str

    status: str

    review_round: int = 0

    dependencies: list[str] = field(default_factory=list)

    task_result: dict[str, Any] = field(default_factory=dict)

    tester_feedback: dict[str, Any] = field(default_factory=dict)

    reviewer_feedback: dict[str, Any] = field(default_factory=dict)

    history: list[dict[str, Any]] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """
        Validate and isolate the context snapshot.

        AgentContext is intentionally not frozen because the current
        architecture does not require Agents to mutate it. Instead,
        mutable input values are deep-copied at construction time.
        """

        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError(
                "AgentContext task_id must be a non-empty string"
            )

        if (
            not isinstance(self.task_title, str)
            or not self.task_title.strip()
        ):
            raise ValueError(
                "AgentContext task_title must be a non-empty string"
            )

        if not isinstance(self.task_description, str):
            raise ValueError(
                "AgentContext task_description must be a string"
            )

        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError(
                "AgentContext role must be a non-empty string"
            )

        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError(
                "AgentContext status must be a non-empty string"
            )

        if not isinstance(self.review_round, int):
            raise ValueError(
                "AgentContext review_round must be an integer"
            )

        if self.review_round < 0:
            raise ValueError(
                "AgentContext review_round must be >= 0"
            )

        if not isinstance(self.dependencies, list):
            raise ValueError(
                "AgentContext dependencies must be a list"
            )

        if not all(
            isinstance(dependency_id, str)
            and dependency_id.strip()
            for dependency_id in self.dependencies
        ):
            raise ValueError(
                "AgentContext dependencies must contain "
                "non-empty strings"
            )

        if not isinstance(self.task_result, dict):
            raise ValueError(
                "AgentContext task_result must be a dictionary"
            )

        if not isinstance(self.tester_feedback, dict):
            raise ValueError(
                "AgentContext tester_feedback must be a dictionary"
            )

        if not isinstance(self.reviewer_feedback, dict):
            raise ValueError(
                "AgentContext reviewer_feedback must be a dictionary"
            )

        if not isinstance(self.history, list):
            raise ValueError(
                "AgentContext history must be a list"
            )

        if not all(
            isinstance(entry, dict)
            for entry in self.history
        ):
            raise ValueError(
                "AgentContext history must contain dictionaries"
            )

        if not isinstance(self.metadata, dict):
            raise ValueError(
                "AgentContext metadata must be a dictionary"
            )

        # ------------------------------------------------------------------
        # Snapshot isolation
        #
        # The Agent must not accidentally observe later mutations to the
        # Task or to dictionaries/lists used to construct this context.
        # ------------------------------------------------------------------
        self.dependencies = deepcopy(self.dependencies)
        self.task_result = deepcopy(self.task_result)
        self.tester_feedback = deepcopy(self.tester_feedback)
        self.reviewer_feedback = deepcopy(self.reviewer_feedback)
        self.history = deepcopy(self.history)
        self.metadata = deepcopy(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the AgentContext into a detached dictionary snapshot.
        """
        return {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "task_description": self.task_description,
            "role": self.role,
            "status": self.status,
            "review_round": self.review_round,
            "dependencies": deepcopy(self.dependencies),
            "task_result": deepcopy(self.task_result),
            "tester_feedback": deepcopy(self.tester_feedback),
            "reviewer_feedback": deepcopy(self.reviewer_feedback),
            "history": deepcopy(self.history),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        context: dict[str, Any],
    ) -> "AgentContext":
        """
        Construct an AgentContext from a dictionary.

        Required fields:
            task_id
            task_title
            task_description
            role
            status
        """

        if not isinstance(context, dict):
            raise ValueError(
                "AgentContext input must be a dictionary"
            )

        required_fields = (
            "task_id",
            "task_title",
            "task_description",
            "role",
            "status",
        )

        missing = [
            field
            for field in required_fields
            if field not in context
        ]

        if missing:
            raise ValueError(
                "AgentContext missing required fields: "
                + ", ".join(missing)
            )

        return cls(
            task_id=context["task_id"],
            task_title=context["task_title"],
            task_description=context["task_description"],
            role=context["role"],
            status=context["status"],
            review_round=context.get("review_round", 0),
            dependencies=context.get("dependencies", []),
            task_result=context.get("task_result", {}),
            tester_feedback=context.get(
                "tester_feedback",
                {},
            ),
            reviewer_feedback=context.get(
                "reviewer_feedback",
                {},
            ),
            history=context.get("history", []),
            metadata=context.get("metadata", {}),
        )

    def __getitem__(self, key: str) -> Any:
        """
        Dictionary-style compatibility access.

        This keeps the context convenient for existing code while the
        canonical representation remains an AgentContext object.
        """
        if key == "task_id":
            return self.task_id

        if key == "task_title":
            return self.task_title

        if key == "task_description":
            return self.task_description

        if key == "role":
            return self.role

        if key == "status":
            return self.status

        if key == "review_round":
            return self.review_round

        if key == "dependencies":
            return self.dependencies

        if key == "task_result":
            return self.task_result

        if key == "tester_feedback":
            return self.tester_feedback

        if key == "reviewer_feedback":
            return self.reviewer_feedback

        if key == "history":
            return self.history

        if key == "metadata":
            return self.metadata

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