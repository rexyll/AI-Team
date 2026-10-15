from __future__ import annotations

from runtime.alerting import AlertRule, AlertSeverity


def reviewer_rejection_rule(*, threshold: int = 2, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold < 1:
        raise ValueError("review rejection threshold must be positive")

    def condition(snapshot) -> bool:
        return any(
            len(getattr(task, "review_history", [])) >= threshold
            and any(str(item.get("status", item.get("outcome", ""))).lower() in {"rejected", "changes_requested"} for item in getattr(task, "review_history", []))
            for task in snapshot.tasks
        )

    return AlertRule(
        rule_id="reviewer.rejection_loop",
        severity=AlertSeverity.WARNING,
        message="reviewer rejection loop exceeded threshold",
        condition=condition,
        cooldown_seconds=cooldown_seconds,
    )


def recovery_rule(*, threshold: int = 2, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold < 1:
        raise ValueError("recovery threshold must be positive")

    def condition(snapshot) -> bool:
        return any(
            sum(1 for item in getattr(task, "retry_history", []) if item.get("retryable") is True) >= threshold
            or len(getattr(task, "review_history", [])) >= threshold + 1
            for task in snapshot.tasks
        )

    return AlertRule(
        rule_id="workflow.recovery_pressure",
        severity=AlertSeverity.WARNING,
        message="workflow recovery pressure exceeded threshold",
        condition=condition,
        cooldown_seconds=cooldown_seconds,
    )
