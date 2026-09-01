from __future__ import annotations

from dataclasses import dataclass

from runtime.model_governance import (
    ModelAdmissionDecision,
    ModelGovernance,
    ModelRoute,
    ModelUsage,
)
from runtime.model_usage import ModelUsageLedger
from runtime.project_scheduler import (
    ProjectAdmissionDecision,
    ProjectExecutionScope,
    ProjectScheduler,
)


@dataclass(frozen=True)
class ModelBudgetSchedulingDecision:
    """Combined project-resource and model-budget admission decision."""

    scope: ProjectExecutionScope
    task_id: str
    admitted: bool
    route: ModelRoute | None = None
    reason: str | None = None


class ModelBudgetProjectScheduler:
    """Add model-budget admission to an existing project scheduler.

    This adapter deliberately does not replace ``ProjectScheduler`` or
    ``ModelGovernance``. Task dependency/resource admission remains owned by
    ``ProjectScheduler``; model budget and route selection remain pure policy
    in ``ModelGovernance``; actual usage remains observationally owned by
    ``ModelUsageLedger``. No reservation or usage mutation occurs here.
    """

    def __init__(
        self,
        scheduler: ProjectScheduler,
        governance: ModelGovernance,
        usage_ledger: ModelUsageLedger,
    ) -> None:
        if not isinstance(scheduler, ProjectScheduler):
            raise TypeError("scheduler must be a ProjectScheduler")
        if not isinstance(governance, ModelGovernance):
            raise TypeError("governance must be a ModelGovernance")
        if not isinstance(usage_ledger, ModelUsageLedger):
            raise TypeError("usage_ledger must be a ModelUsageLedger")
        self._scheduler = scheduler
        self._governance = governance
        self._usage_ledger = usage_ledger

    @property
    def scheduler(self) -> ProjectScheduler:
        return self._scheduler

    @property
    def governance(self) -> ModelGovernance:
        return self._governance

    @property
    def usage_ledger(self) -> ModelUsageLedger:
        return self._usage_ledger

    @property
    def scope(self) -> ProjectExecutionScope:
        return self._scheduler.scope

    def decide(
        self,
        task_id: str,
        *,
        model_request: ModelUsage,
        primary_healthy: bool = True,
    ) -> ModelBudgetSchedulingDecision:
        if not isinstance(model_request, ModelUsage):
            raise TypeError("model_request must be a ModelUsage")
        project_decision = self._scheduler.decide(task_id)
        if not project_decision.admitted:
            return ModelBudgetSchedulingDecision(
                scope=self.scope,
                task_id=task_id,
                admitted=False,
                reason=project_decision.reason,
            )

        model_decision: ModelAdmissionDecision = self._governance.decide(
            self.scope.project_id,
            usage=self._usage_ledger.usage_for(self.scope.project_id),
            request=model_request,
            primary_healthy=primary_healthy,
        )
        if not model_decision.admitted:
            return ModelBudgetSchedulingDecision(
                scope=self.scope,
                task_id=task_id,
                admitted=False,
                reason=model_decision.reason,
            )
        return ModelBudgetSchedulingDecision(
            scope=self.scope,
            task_id=task_id,
            admitted=True,
            route=model_decision.route,
            reason=model_decision.reason,
        )
