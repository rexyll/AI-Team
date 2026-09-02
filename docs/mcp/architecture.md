# AI-Team Local MCP Bridge Architecture — Phase 6

## Purpose

The bridge exposes a deliberately narrow MCP surface over an authorized local
AI-Team repository. It is an adapter, not a second runtime/security system.

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
                    |
                    v
             host-owned workflow
```

## Phase 6 orchestration boundary

`MCPOrchestrationBoundary` is a capability boundary over the host-owned
runtime. It does not expose `Task`, agent, or workflow objects directly. MCP
receives stable projections only.

The Phase 6 surface is split into inspection and execution:

- task inspection: list tasks, fetch one task, list ready tasks;
- agent inspection: list registered roles without exposing agent instances;
- capability discovery: report whether task/agent inspection and workflow
  execution are configured;
- workflow execution: available only when a host explicitly injects execution.

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
its existing `TaskManager` and `AgentRouter` and delegates execution to the
Orchestrator's canonical per-task execution entrypoint. Consequently MCP task
execution inherits the existing dependency scheduling, developer selection,
workflow gates, retry/recovery, resource governance, checkpoint, event, and
terminal-state behavior instead of introducing parallel orchestration logic.

MCP execution is guarded in two layers:

1. `TaskManager.ensure_executable()` supplies the canonical dependency/state
   admission semantics.
2. `MCPOrchestrationBoundary` adds a non-blocking per-task lock and rejects a
   task that is already active. Different task IDs are not serialized by this
   lock.

The boundary returns a fresh task projection after execution. Mutable runtime
objects never cross the MCP protocol boundary.

The standalone MCP server still does **not** construct an Orchestrator or
agents implicitly. Host composition must be explicit. This preserves the
fail-closed property and avoids creating a second runtime with different
lifecycle or authorization semantics.

## Phase 5 public MCP surface

The existing workspace and Git surface remains unchanged:

- `bridge_health`
- `workspace_validate_path`
- `workspace_list_files`
- `workspace_read_file`
- `workspace_search_text`
- `workspace_write_file`
- `workspace_delete_file`
- `git_status`
- `git_diff`
- `git_log`
- `git_show`
- `git_branch`
- `git_rev_parse`
- `git_add`
- `git_commit`

Phase 6 adds the orchestration capability family:

- `task_list`
- `task_get`
- `task_ready`
- `agent_list`
- `workflow_capabilities`
- `task_execute`

The server's workspace, Git, terminal, and network authorization policies are
not widened by the orchestration boundary.

## Security rules

Orchestration must use existing host-owned lifecycle and routing semantics.
The MCP layer must not mutate `Task.status`, task context, retry counters, or
agent registries directly. Execution, when enabled, crosses the host
Orchestrator and therefore the canonical `TaskManager`/`TaskWorkflow`
semantics.

No orchestration tool may provide a generic method name, Python object,
filesystem handle, subprocess handle, environment variable, or network client
to the MCP caller.

Cancellation and other control-plane mutations require a separate explicit
authorization contract and are not included in Phase 6.2.

## Earlier workspace and Git controls

All workspace reads and mutations continue to cross the canonical
`security.workspace.WorkspaceSandbox`. Git operations continue through
`HostGitOperationService` and the allow-listed `tools.git.git_command` path.
`.git` remains blocked as a direct workspace metadata interface, Git output
remains bounded, and stdout remains reserved for MCP stdio protocol traffic.
