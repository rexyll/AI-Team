from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """Immutable-in-practice execution snapshot passed to an Agent."""

    task_id: str
    task_title: str
    task_description: str
    role: str
    status: str
    review_round: int = 0
    dependencies: list[str] = field(default_factory=list)
    dependency_context: dict[str, Any] = field(default_factory=dict)
    task_result: dict[str, Any] = field(default_factory=dict)
    tester_feedback: dict[str, Any] = field(default_factory=dict)
    qa_feedback: dict[str, Any] = field(default_factory=dict)
    reviewer_feedback: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    test_history: list[dict[str, Any]] = field(default_factory=list)
    review_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("AgentContext task_id must be a non-empty string")
        if not isinstance(self.task_title, str) or not self.task_title.strip():
            raise ValueError("AgentContext task_title must be a non-empty string")
        if not isinstance(self.task_description, str):
            raise ValueError("AgentContext task_description must be a string")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("AgentContext role must be a non-empty string")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("AgentContext status must be a non-empty string")
        if not isinstance(self.review_round, int):
            raise ValueError("AgentContext review_round must be an integer")
        if self.review_round < 0:
            raise ValueError("AgentContext review_round must be >= 0")
        if not isinstance(self.dependencies, list):
            raise ValueError("AgentContext dependencies must be a list")
        if not all(
            isinstance(dependency_id, str) and dependency_id.strip()
            for dependency_id in self.dependencies
        ):
            raise ValueError(
                "AgentContext dependencies must contain non-empty strings"
            )
        if not isinstance(self.dependency_context, dict):
            raise ValueError(
                "AgentContext dependency_context must be a dictionary"
            )
        if not isinstance(self.task_result, dict):
            raise ValueError("AgentContext task_result must be a dictionary")
        if not isinstance(self.tester_feedback, dict):
            raise ValueError(
                "AgentContext tester_feedback must be a dictionary"
            )
        if not isinstance(self.qa_feedback, dict):
            raise ValueError(
                "AgentContext qa_feedback must be a dictionary"
            )
        if not isinstance(self.reviewer_feedback, dict):
            raise ValueError(
                "AgentContext reviewer_feedback must be a dictionary"
            )
        if not isinstance(self.history, list):
            raise ValueError("AgentContext history must be a list")
        if not all(isinstance(entry, dict) for entry in self.history):
            raise ValueError(
                "AgentContext history must contain dictionaries"
            )
        if not isinstance(self.test_history, list):
            raise ValueError("AgentContext test_history must be a list")
        if not all(isinstance(entry, dict) for entry in self.test_history):
            raise ValueError(
                "AgentContext test_history must contain dictionaries"
            )
        if not isinstance(self.review_history, list):
            raise ValueError("AgentContext review_history must be a list")
        if not all(isinstance(entry, dict) for entry in self.review_history):
            raise ValueError(
                "AgentContext review_history must contain dictionaries"
            )
        if not isinstance(self.metadata, dict):
            raise ValueError("AgentContext metadata must be a dictionary")

        self.dependencies = deepcopy(self.dependencies)
        self.dependency_context = deepcopy(self.dependency_context)
        self.task_result = deepcopy(self.task_result)
        self.tester_feedback = deepcopy(self.tester_feedback)
        self.qa_feedback = deepcopy(self.qa_feedback)
        self.reviewer_feedback = deepcopy(self.reviewer_feedback)
        self.history = deepcopy(self.history)
        self.test_history = deepcopy(self.test_history)
        self.review_history = deepcopy(self.review_history)
        self.metadata = deepcopy(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a detached dictionary.

        Optional context extensions are emitted only when populated so the
        pre-3.3 serialized AgentContext shape remains backward compatible.
        """
        result = {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "task_description": self.task_description,
            "role": self.role,
            "status": self.status,
            "review_round": self.review_round,
            "dependencies": deepcopy(self.dependencies),
            "task_result": deepcopy(self.task_result),
            "tester_feedback": deepcopy(self.tester_feedback),
            "qa_feedback": deepcopy(self.qa_feedback),
            "reviewer_feedback": deepcopy(self.reviewer_feedback),
            "history": deepcopy(self.history),
            "metadata": deepcopy(self.metadata),
        }

        if self.dependency_context:
            result["dependency_context"] = deepcopy(
                self.dependency_context
            )
        if self.test_history:
            result["test_history"] = deepcopy(self.test_history)
        if self.review_history:
            result["review_history"] = deepcopy(self.review_history)

        return result

    @classmethod
    def from_dict(cls, context: dict[str, Any]) -> "AgentContext":
        if not isinstance(context, dict):
            raise ValueError("AgentContext input must be a dictionary")

        required_fields = (
            "task_id",
            "task_title",
            "task_description",
            "role",
            "status",
        )

        missing = [field for field in required_fields if field not in context]
        if missing:
            raise ValueError(
                "AgentContext missing required fields: " + ", ".join(missing)
            )

        return cls(
            task_id=context["task_id"],
            task_title=context["task_title"],
            task_description=context["task_description"],
            role=context["role"],
            status=context["status"],
            review_round=context.get("review_round", 0),
            dependencies=context.get("dependencies", []),
            dependency_context=context.get("dependency_context", {}),
            task_result=context.get("task_result", {}),
            tester_feedback=context.get("tester_feedback", {}),
            qa_feedback=context.get("qa_feedback", {}),
            reviewer_feedback=context.get("reviewer_feedback", {}),
            history=context.get("history", []),
            test_history=context.get("test_history", []),
            review_history=context.get("review_history", []),
            metadata=context.get("metadata", {}),
        )

    def __getitem__(self, key: str) -> Any:
        values = self.to_dict()
        if key not in values:
            raise KeyError(key)
        return values[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default
