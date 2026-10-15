from __future__ import annotations

from runtime.alerting import AlertRule, AlertSeverity


def failure_rate_rule(*, threshold: float = 0.5, cooldown_seconds: float = 300.0) -> AlertRule:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("failure-rate threshold must be between 0 and 1")
    return AlertRule(
        rule_id="workflow.failure_rate",
        severity=AlertSeverity.CRITICAL,
        message="workflow failure rate exceeded threshold",
        condition=lambda snapshot: snapshot.workflow.total_tasks > 0
        and snapshot.workflow.failed / snapshot.workflow.total_tasks >= threshold,
        cooldown_seconds=cooldown_seconds,
    )


def latency_rule(*, threshold_seconds: float = 60.0, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold_seconds < 0:
        raise ValueError("latency threshold must be non-negative")
    return AlertRule(
        rule_id="workflow.latency",
        severity=AlertSeverity.WARNING,
        message="workflow average duration exceeded threshold",
        condition=lambda snapshot: snapshot.workflow.average_duration_seconds is not None
        and snapshot.workflow.average_duration_seconds >= threshold_seconds,
        cooldown_seconds=cooldown_seconds,
    )


def retry_rule(*, threshold: int = 3, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold < 1:
        raise ValueError("retry threshold must be positive")
    return AlertRule(
        rule_id="workflow.retries",
        severity=AlertSeverity.WARNING,
        message="workflow retry count exceeded threshold",
        condition=lambda snapshot: snapshot.workflow.retries >= threshold,
        cooldown_seconds=cooldown_seconds,
    )
