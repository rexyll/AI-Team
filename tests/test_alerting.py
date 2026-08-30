from dataclasses import dataclass

import pytest

from runtime.alerting import AlertManager, AlertRule, AlertSeverity


@dataclass
class Snapshot:
    failed: int = 0
    latency: float = 0.0


def test_alert_rule_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        AlertRule("", AlertSeverity.WARNING, "x", lambda _: True)
    with pytest.raises(ValueError):
        AlertRule("x", AlertSeverity.WARNING, "x", lambda _: True, cooldown_seconds=-1)


def test_alert_manager_deduplicates_with_cooldown():
    now = [100.0]
    manager = AlertManager(clock=lambda: now[0])
    manager.register(AlertRule("failure-rate", AlertSeverity.CRITICAL, "too many failures", lambda s: s.failed >= 3, cooldown_seconds=30))

    snapshot = Snapshot(failed=3)
    assert len(manager.evaluate(snapshot, dedup_key="project-A")) == 1
    assert manager.evaluate(snapshot, dedup_key="project-A") == ()

    now[0] += 30
    assert len(manager.evaluate(snapshot, dedup_key="project-A")) == 1


def test_alert_deduplication_is_scoped_by_key():
    manager = AlertManager(clock=lambda: 100.0)
    manager.register(AlertRule("failure", AlertSeverity.WARNING, "failure", lambda s: s.failed > 0, cooldown_seconds=60))
    snapshot = Snapshot(failed=1)

    assert len(manager.evaluate(snapshot, dedup_key="task-A")) == 1
    assert len(manager.evaluate(snapshot, dedup_key="task-B")) == 1


def test_alert_manager_reset_allows_re_emission():
    manager = AlertManager(clock=lambda: 100.0)
    manager.register(AlertRule("latency", AlertSeverity.WARNING, "slow", lambda s: s.latency > 10, cooldown_seconds=60))
    snapshot = Snapshot(latency=20)
    assert len(manager.evaluate(snapshot)) == 1
    manager.reset()
    assert len(manager.evaluate(snapshot)) == 1
