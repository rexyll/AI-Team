from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


TIER_NAMES = (
    "system_contract",
    "project_facts",
    "task_facts",
    "current_work_evidence",
    "recent_interaction",
    "historical_evidence",
)


@dataclass(frozen=True)
class SemanticContextTiers:
    """Stable semantic partition of Agent context.

    Tiers are deliberately descriptive rather than size-based. Compaction and
    budget allocation can later assign different retention policies without
    changing the meaning of the underlying context.
    """

    system_contract: dict[str, Any]
    project_facts: dict[str, Any]
    task_facts: dict[str, Any]
    current_work_evidence: dict[str, Any]
    recent_interaction: list[dict[str, Any]]
    historical_evidence: dict[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "system_contract",
            "project_facts",
            "task_facts",
            "current_work_evidence",
            "historical_evidence",
        ):
            value = getattr(self, name)
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be a dictionary")
        if not isinstance(self.recent_interaction, list):
            raise ValueError("recent_interaction must be a list")
        if not all(isinstance(item, dict) for item in self.recent_interaction):
            raise ValueError("recent_interaction must contain dictionaries")

    def to_dict(self) -> dict[str, Any]:
        return deepcopy({
            "system_contract": self.system_contract,
            "project_facts": self.project_facts,
            "task_facts": self.task_facts,
            "current_work_evidence": self.current_work_evidence,
            "recent_interaction": self.recent_interaction,
            "historical_evidence": self.historical_evidence,
        })


def build_semantic_context_tiers(
    *,
    role: str,
    task_id: str,
    task_title: str,
    task_description: str,
    status: str,
    dependencies: list[str] | None = None,
    dependency_context: dict[str, Any] | None = None,
    task_result: dict[str, Any] | None = None,
    tester_feedback: dict[str, Any] | None = None,
    reviewer_feedback: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    test_history: list[dict[str, Any]] | None = None,
    review_history: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SemanticContextTiers:
    """Partition canonical Agent context without changing its source data."""
    return SemanticContextTiers(
        system_contract={"role": role},
        project_facts=deepcopy(metadata or {}),
        task_facts={
            "task_id": task_id,
            "task_title": task_title,
            "task_description": task_description,
            "status": status,
            "dependencies": list(dependencies or []),
        },
        current_work_evidence={
            "task_result": deepcopy(task_result or {}),
            "tester_feedback": deepcopy(tester_feedback or {}),
            "reviewer_feedback": deepcopy(reviewer_feedback or {}),
            "dependency_context": deepcopy(dependency_context or {}),
        },
        recent_interaction=deepcopy(history or [])[-8:],
        historical_evidence={
            "test_history": deepcopy(test_history or []),
            "review_history": deepcopy(review_history or []),
        },
    )
