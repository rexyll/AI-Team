# AI-Team Extension Examples

These examples target the current canonical runtime contracts on the development branch.

## Custom Agent

`custom_agent.py` shows the smallest supported Agent extension:

- subclass `BaseAgent`
- expose a stable `role`
- accept the canonical `Task`
- return `AgentResult`

Run from the repository root:

```powershell
python examples/custom_agent.py
```

## Custom LLM

`custom_llm.py` shows the provider boundary:

- implement `BaseLLM.generate()`
- keep provider details outside orchestration
- inject the implementation into an Agent when needed

Run:

```powershell
python examples/custom_llm.py
```

For deterministic tests, prefer the built-in `MockLLM` rather than a network provider.

## Custom Tool

`custom_tool.py` shows registration through `ToolRegistry` with a matching function-call schema.

A registry is not an authorization boundary. Production tool execution must still pass the existing argument validation, permission policy, and workspace sandbox/security layers.

Run:

```powershell
python examples/custom_tool.py
```

The example deliberately uses a pure in-memory transformation and does not bypass protected filesystem or command execution.

## Persistence and Query

`persistence_query.py` demonstrates durable workflow-event storage followed by read-only operational querying.

Run:

```powershell
python examples/persistence_query.py
```

The example writes only under its configured example data directory. Query construction is read-only and does not mutate the event store.

## Contract rule

Examples are documentation of the current API, not compatibility shims for legacy APIs. When a canonical runtime contract changes, update the example and its contract test in the same DevPlan node.
