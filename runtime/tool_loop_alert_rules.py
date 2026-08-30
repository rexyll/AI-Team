from __future__ import annotations

from runtime.alerting import AlertRule, AlertSeverity


def _telemetry(snapshot):
    return getattr(snapshot, "tool_calls", ())


def duplicate_tool_call_rule(*, threshold: int = 3, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold < 1:
        raise ValueError("duplicate tool-call threshold must be positive")

    def condition(snapshot) -> bool:
        return sum(1 for item in _telemetry(snapshot) if getattr(item, "duplicate_of", None) is not None) >= threshold

    return AlertRule(
        rule_id="tool_loop.duplicates",
        severity=AlertSeverity.WARNING,
        message="tool-loop duplicate calls exceeded threshold",
        condition=condition,
        cooldown_seconds=cooldown_seconds,
    )


def retry_tool_call_rule(*, threshold: int = 2, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold < 1:
        raise ValueError("retry tool-call threshold must be positive")

    def condition(snapshot) -> bool:
        return sum(1 for item in _telemetry(snapshot) if getattr(item, "retry_of", None) is not None) >= threshold

    return AlertRule(
        rule_id="tool_loop.retries",
        severity=AlertSeverity.WARNING,
        message="tool-loop retries exceeded threshold",
        condition=condition,
        cooldown_seconds=cooldown_seconds,
    )


def result_volume_rule(*, threshold_chars: int = 100_000, cooldown_seconds: float = 300.0) -> AlertRule:
    if threshold_chars < 1:
        raise ValueError("tool result volume threshold must be positive")

    def condition(snapshot) -> bool:
        return sum(max(0, int(getattr(item, "result_chars", 0))) for item in _telemetry(snapshot)) >= threshold_chars

    return AlertRule(
        rule_id="tool_loop.result_volume",
        severity=AlertSeverity.WARNING,
        message="tool-loop result volume exceeded threshold",
        condition=condition,
        cooldown_seconds=cooldown_seconds,
    )
