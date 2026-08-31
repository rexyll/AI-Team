# Operational observability example

This example demonstrates the existing operational read and alerting contracts without a real provider or network dependency.

It builds a deterministic set of tasks, renders an `ObservabilityDashboard` snapshot, evaluates an `AlertManager` rule, and sends emitted alerts through the provider-independent `AlertDeliveryManager` to a console sink.

Run from the repository root:

```powershell
python examples/operational_observability/run.py
```

The example intentionally uses the production dashboard, alerting, and delivery classes. It does not introduce a second monitoring implementation.
