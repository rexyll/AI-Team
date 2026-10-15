# Operational Troubleshooting

Use this guide after the baseline `pytest -q` suite is green.

## CLI / workflow startup

If startup fails before task execution, first validate configuration. Check provider/model names and required environment variables using `docs/configuration_reference.md` and `docs/production_configuration.md`.

If a run appears stuck in Developer execution, inspect the tool-loop budget and the task's latest execution/audit information. The runtime intentionally bounds tool-loop work rather than allowing an unbounded model loop.

## Task recovery

A stale heartbeat and lack of progress are distinct signals. Recovery must not take over a task solely because one timestamp is old. An active execution lease prevents takeover until the lease expires according to the lease policy.

After a crash, workflow checkpoints and the recovery path determine which tasks can be resumed. Completed work must not be replayed as a new completion side effect.

## Observability

For operational diagnosis, correlate workflow events, structured logs, metrics, and traces by their supported identity fields. Do not turn `trace_id` or `span_id` into high-cardinality metric labels.

The dashboard is a read-only operational view. It should not become a second source of task truth.

## Alerting and delivery

Alert evaluation is provider-independent. Delivery is separate from alert creation and may be retried according to the configured delivery policy. Repeated delivery of the same stable delivery identity must remain idempotent at the durable commit boundary.

Webhook delivery is subject to the same network-egress security boundary as other runtime network operations. A rejected destination must not invoke the underlying transport.

## Security incidents

If output contains a credential, token, password, or other secret, stop the run and rotate the affected credential. Do not paste the secret into an issue or log. Inspect the redaction/audit boundaries and use the security regression suite before resuming normal development.

For suspected prompt injection, treat task descriptions, dependency outputs, repository files, tool results, and test output as untrusted data. Do not weaken the tool or workspace authorization boundary to make a run succeed.

## Regression workflow

For a focused change:

```powershell
pytest tests/<focused_contract_test>.py -q
pytest -q
```

Only update `DevPlan.md` after the full acceptance suite is green. If the full suite fails, preserve the failure as evidence and fix the smallest affected contract rather than weakening the test.
