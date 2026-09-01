from __future__ import annotations

from dataclasses import dataclass, replace


class ModelGovernanceError(ValueError):
    """Raised when a model-governance policy or admission request is invalid."""


@dataclass(frozen=True)
class ModelRoute:
    """Immutable provider/model route selected for one runtime role."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ModelGovernanceError("provider must be a non-empty string")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ModelGovernanceError("model must be a non-empty string")
        object.__setattr__(self, "provider", self.provider.strip().lower())
        object.__setattr__(self, "model", self.model.strip())


@dataclass(frozen=True)
class ProjectModelBudget:
    """Immutable per-project token/call budget."""

    max_input_tokens: int
    max_output_tokens: int
    max_llm_calls: int

    def __post_init__(self) -> None:
        for name in ("max_input_tokens", "max_output_tokens", "max_llm_calls"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ModelGovernanceError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ModelUsage:
    """Immutable usage snapshot used for deterministic admission decisions."""

    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "llm_calls"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ModelGovernanceError(f"{name} must be a non-negative integer")

    def add(self, *, input_tokens: int = 0, output_tokens: int = 0, llm_calls: int = 0) -> "ModelUsage":
        return replace(
            self,
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
            llm_calls=self.llm_calls + llm_calls,
        )


@dataclass(frozen=True)
class ModelGovernancePolicy:
    """Project-scoped route, budget, and optional fallback route."""

    project_id: str
    primary: ModelRoute
    budget: ProjectModelBudget
    fallback: ModelRoute | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ModelGovernanceError("project_id must be a non-empty string")
        if not isinstance(self.primary, ModelRoute):
            raise ModelGovernanceError("primary must be a ModelRoute")
        if not isinstance(self.budget, ProjectModelBudget):
            raise ModelGovernanceError("budget must be a ProjectModelBudget")
        if self.fallback is not None and not isinstance(self.fallback, ModelRoute):
            raise ModelGovernanceError("fallback must be a ModelRoute or None")
        object.__setattr__(self, "project_id", self.project_id.strip())


@dataclass(frozen=True)
class ModelAdmissionDecision:
    """Pure model admission result; no usage mutation occurs here."""

    admitted: bool
    route: ModelRoute | None
    reason: str | None = None


class ModelGovernance:
    """Evaluate project-scoped LLM admission without becoming a runtime owner."""

    def __init__(self, policies: list[ModelGovernancePolicy]) -> None:
        if not isinstance(policies, list):
            raise TypeError("policies must be a list")
        self._policies: dict[str, ModelGovernancePolicy] = {}
        for policy in policies:
            if not isinstance(policy, ModelGovernancePolicy):
                raise TypeError("all policies must be ModelGovernancePolicy instances")
            if policy.project_id in self._policies:
                raise ModelGovernanceError(f"duplicate project policy: {policy.project_id}")
            self._policies[policy.project_id] = policy

    def policy_for(self, project_id: str) -> ModelGovernancePolicy:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        try:
            return self._policies[project_id.strip()]
        except KeyError as exc:
            raise KeyError(f"Unknown project: {project_id}") from exc

    @staticmethod
    def _within_budget(policy: ModelGovernancePolicy, usage: ModelUsage, request: ModelUsage) -> tuple[bool, str | None]:
        budget = policy.budget
        if usage.input_tokens + request.input_tokens > budget.max_input_tokens:
            return False, "project input-token budget exceeded"
        if usage.output_tokens + request.output_tokens > budget.max_output_tokens:
            return False, "project output-token budget exceeded"
        if usage.llm_calls + request.llm_calls > budget.max_llm_calls:
            return False, "project LLM-call budget exceeded"
        return True, None

    def decide(
        self,
        project_id: str,
        *,
        usage: ModelUsage,
        request: ModelUsage,
        primary_healthy: bool = True,
    ) -> ModelAdmissionDecision:
        if not isinstance(usage, ModelUsage) or not isinstance(request, ModelUsage):
            raise TypeError("usage and request must be ModelUsage instances")
        policy = self.policy_for(project_id)
        within, reason = self._within_budget(policy, usage, request)
        if not within:
            return ModelAdmissionDecision(False, None, reason)
        if primary_healthy:
            return ModelAdmissionDecision(True, policy.primary)
        if policy.fallback is not None:
            return ModelAdmissionDecision(True, policy.fallback, "primary route unhealthy; fallback selected")
        return ModelAdmissionDecision(False, None, "primary route unhealthy and no fallback is configured")
