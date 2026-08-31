from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.alerting import AlertManager, AlertRule, AlertSeverity
from runtime.alert_delivery import AlertDelivery, AlertDeliveryManager, DeliveryStatus
from runtime.observability_dashboard import ObservabilityDashboard
from runtime.task import Task


class ConsoleSink:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def deliver(self, delivery: AlertDelivery) -> None:
        message = f"alert={delivery.alert.rule_id} severity={delivery.alert.severity.value} message={delivery.alert.message}"
        self.messages.append(message)
        print(message)


def main() -> int:
    tasks = [
        Task(id="EXAMPLE-001", title="Build feature", description="Deterministic demo task", role="developer", status="completed"),
        Task(id="EXAMPLE-002", title="Investigate failure", description="Deterministic demo failure", role="tester", status="failed", error="example failure"),
        Task(id="EXAMPLE-003", title="Continue work", description="Deterministic active task", role="developer", status="running"),
    ]

    dashboard = ObservabilityDashboard()
    snapshot = dashboard.snapshot(tasks, project_id="EXAMPLE-OPS")
    print(
        f"workflow total={snapshot.workflow.total_tasks} completed={snapshot.workflow.completed} "
        f"failed={snapshot.workflow.failed} active={snapshot.workflow.active} "
        f"success_rate={snapshot.workflow.success_rate:.2f}"
    )

    alerts = AlertManager(clock=lambda: 100.0)
    alerts.register(AlertRule(
        rule_id="failed-tasks",
        severity=AlertSeverity.WARNING,
        message="workflow contains failed tasks",
        condition=lambda value: value.workflow.failed > 0,
    ))
    emitted = alerts.evaluate(snapshot, dedup_key=snapshot.project_id or "example")

    sink = ConsoleSink()
    delivery = AlertDeliveryManager(sink)
    for index, alert in enumerate(emitted, start=1):
        delivery.deliver(
            AlertDelivery(
                f"{snapshot.project_id}:alert:{index}",
                alert,
                status=DeliveryStatus.RETRYING,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
