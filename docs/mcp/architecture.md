# AI-Team Local MCP Bridge Architecture — Phase 6.3

## Purpose

The bridge exposes a deliberately narrow MCP surface over an authorized local
AI-Team repository. It is an adapter, not a second runtime or audit store.

```text
MCP Host
   |
   v
mcp_bridge
   |
   +-- workspace policy
   +-- mutation policy
   +-- Git capability policy
   +-- orchestration capability policy
   +-- execution observability
   |
   +------------------------------+
   |                              |
   v                              v
workspace / Git adapters    MCPOrchestrationBoundary
                                   |
                    +--------------+--------------+
                    |                             |
                    v                             v
               TaskManager                    AgentRouter
                    |                             |
                    +-------------+---------------+
                                  v
                         host-owned Orchestrator
                                  |
                                  v
                         WorkflowEventLog
```

## Phase 6 orchestration boundary

`MCPOrchestrationBoundary` is a capability boundary over the host-owned
runtime. It does not expose `Task`, agent, or workflow objects directly. MCP
receives stable projections only.

The surface is split into inspection, execution, and execution observability:

- task inspection: list tasks, fetch one task, list ready tasks;
- agent inspection: list registered roles without exposing agent instances;
- capability discovery: report whether task/agent inspection, workflow
  execution, and execution observability are configured;
- workflow execution: available only when a host explicitly injects execution;
- execution history: return bounded MCP execution lifecycle records for one task.

Task projections contain identity, title, role, lifecycle status,
dependencies, error state, review/retry counters, and cancellation state.
Runtime context, tool history, agent objects, result payloads, credentials,
and arbitrary runtime internals are not exposed by the projection.

## Phase 6.2 host runtime composition

Production integration is created with:

```python
boundary = MCPOrchestrationBoundary.from_orchestrator(orchestrator)
server = create_server(config, orchestration=boundary)
```

The supplied `Orchestrator` remains the sole runtime owner. The adapter reuses
its existing `TaskManager` and `AgentRouter` and delegates execution through
its public `execute_task()` entrypoint. MCP therefore cannot accidentally
create a parallel workflow runtime or bypass retry/recovery/resource/checkpoint
semantics.

`Orchestrator.execute_task(task_id, execution_id=...)` is now the supported
external execution entrypoint. Internal scheduler execution continues to use
the same `_execute_task()` implementation, so there is only one task execution
implementation.

Execution is guarded in two layers:

1. `TaskManager.ensure_executable()` supplies canonical dependency/state
   admission semantics.
2. `MCPOrchestrationBoundary` adds a non-blocking per-task lock and rejects a
   task that is already active. Different task IDs are not serialized.

## Phase 6.3 execution correlation and audit

Every MCP-triggered execution receives a UUID `execution_id`. The ID is passed
from the MCP boundary into the host `Orchestrator`, and the host records it in
the task's internal execution context and lifecycle events. It is also returned
in the `task_execute` response so a caller can correlate the result with the
runtime event stream.

The MCP boundary records two explicit adapter events in the existing canonical
`WorkflowEventLog` when an event log and project identity are configured:

- `mcp_task_execution_requested`
- `mcp_task_execution_completed` or `mcp_task_execution_failed`

Each event carries `source=mcp` and the same `execution_id`. No second audit
store is created by MCP. `task_execution_history` is a read-only projection of
these existing workflow events, bounded to at most 200 records per request.

This gives the control plane a traceable chain:

```text
MCP task_execute
      |
      +-- execution_id
      |
      +--> mcp_task_execution_requested
      |
      +--> Orchestrator.execute_task(execution_id=...)
      |        |
      |        +--> task_started / workflow events / retry / failure
      |
      +--> mcp_task_execution_completed|failed
      |
      +--> task_execute response {execution_id, task projection}
```

The MCP layer does not copy arbitrary task context or workflow payloads into
its audit response. Only bounded lifecycle metadata is projected.

## Public MCP surface

Workspace and Git tools remain unchanged. Phase 6 adds:

- `task_list`
- `task_get`
- `task_ready`
- `agent_list`
- `workflow_capabilities`
- `task_execution_history`
- `task_execute`

Terminal, network, cancellation, and other control-plane mutations remain
disabled. The standalone MCP server still does **not** construct an
Orchestrator or agents implicitly; host composition must be explicit.

## Security rules

Orchestration must use existing host-owned lifecycle and routing semantics.
The MCP layer must not mutate `Task.status`, task context, retry counters, or
agent registries directly. Execution crosses the host `Orchestrator` and its
canonical `TaskManager`/`TaskWorkflow` semantics.

No orchestration tool may provide a generic method name, Python object,
filesystem handle, subprocess handle, environment variable, or network client
to the MCP caller.

All workspace reads and mutations continue to cross the canonical
`security.workspace.WorkspaceSandbox`. Git operations continue through
`HostGitOperationService` and the allow-listed `tools.git.git_command` path.
`.git` remains blocked as a direct workspace metadata interface, Git output
remains bounded, and stdout remains reserved for MCP stdio protocol traffic.
