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

`MCPOrchestrationBoundary` is a separate capability boundary over the
host-owned runtime. It does not expose `Task`, agent, or workflow objects
directly. MCP receives stable projections only.

The initial Phase 6 surface is intentionally split into inspection and
execution:

- task inspection: list tasks, fetch one task, list ready tasks;
- agent inspection: list registered roles without exposing agent instances;
- capability discovery: report whether task/agent inspection and workflow
  execution are configured;
- workflow execution: available only when a host explicitly injects a
  workflow factory.

Task projections contain identity, title, role, lifecycle status,
dependencies, error state, review/retry counters, and cancellation state.
Runtime context, tool history, agent objects, result payloads, credentials,
and arbitrary runtime internals are not exposed by the projection.

Workflow execution is **fail-closed**. The standalone MCP server does not
construct agents or workflows implicitly. Without an injected host-owned
workflow factory, `task_execute` remains unavailable and returns a bounded
configuration error. This prevents the MCP adapter from silently creating a
second orchestration runtime with different authorization or lifecycle rules.

The workflow factory must return an object exposing `execute(task_id)`. The
result is projected back to the same bounded task representation, so the MCP
caller never receives the mutable Task object.

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
agent registries directly. Execution, when enabled, crosses the injected
workflow object and therefore the canonical `TaskWorkflow`/`TaskManager`
semantics.

No orchestration tool may provide a generic method name, Python object,
filesystem handle, subprocess handle, environment variable, or network client
to the MCP caller.

## Remaining Phase 6 work

The current boundary establishes the safe read/execute contract. The next
increment should integrate it with the production server's actual runtime
composition and add protocol-level tests for the Phase 6 tool registration,
health/capability reporting, disabled-by-default execution, and bounded task
projections. Cancellation and other control-plane mutations require a separate
explicit authorization contract and are not included in this increment.

## Earlier workspace and Git controls

All workspace reads and mutations continue to cross the canonical
`security.workspace.WorkspaceSandbox`. Git operations continue through
`HostGitOperationService` and the allow-listed `tools.git.git_command` path.
`.git` remains blocked as a direct workspace metadata interface, Git output
remains bounded, and stdout remains reserved for MCP stdio protocol traffic.
