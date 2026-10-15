# Deterministic Review Loop

This example demonstrates the production Developer → Tester → Reviewer workflow without an external LLM provider.

## Run

From the repository root:

```powershell
python examples/review_loop/run.py
```

The example creates one ready task, registers deterministic role agents with `AgentRouter`, and executes it through `TaskWorkflow`.

Expected output ends with a completed task, for example:

```text
task=EXAMPLE-REVIEW-001 status=completed developer_calls=1 review_round=1
```

## What it demonstrates

1. A task starts in the `ready` state.
2. `TaskWorkflow` runs the Developer stage.
3. Tester evidence is linked to the Developer result.
4. Reviewer evidence is linked to the Tester result.
5. Reviewer approval moves the task to `completed`.

The agents are local deterministic test doubles. No API key, network connection, or external provider is required.
