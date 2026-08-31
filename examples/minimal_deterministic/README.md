# Minimal deterministic example

This example demonstrates the smallest deterministic task execution flow without an external LLM provider.

## Run

From the repository root:

```powershell
python examples/minimal_deterministic/run.py
```

Expected result is deterministic: the single task finishes with `completed`.

The example uses the production `Task` / `TaskManager` contracts and the repository's `MockAgent`; it does not introduce a second runtime implementation.
