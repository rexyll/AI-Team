# AI-Team Local MCP Bridge Architecture — Phase 7

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
   +-- controlled terminal policy
   |
   +------------------------------+
   |                              |
   v                              v
workspace / Git / terminal    MCPOrchestrationBoundary
adapters                            |
                         host-owned Orchestrator
                                  |
                                  v
                         WorkflowEventLog
```

## Phase 6 orchestration boundary

`MCPOrchestrationBoundary` is a capability boundary over the host-owned
runtime. It exposes stable task and agent projections, controlled workflow
execution, execution history/status, and idempotency without exposing runtime
objects or creating a second orchestration runtime.

Production integration is created with:

```python
boundary = MCPOrchestrationBoundary.from_orchestrator(orchestrator)
server = create_server(config, orchestration=boundary)
```

The supplied `Orchestrator` remains the sole runtime owner. MCP execution uses
its public `execute_task(task_id, execution_id=...)` entrypoint, preserving the
existing TaskManager, retry/recovery, resource, and checkpoint semantics.

Every MCP-triggered execution receives an opaque UUID `execution_id`. MCP
records `mcp_task_execution_requested` and a matching completed/failed event
in the existing canonical `WorkflowEventLog`. Execution status and history are
projections of that log. An optional `idempotency_key` is atomically bound to a
single task execution and fails closed when canonical execution observability
is unavailable.

## Phase 7 controlled terminal boundary

Terminal access is an **optional host capability**, unlike the read/write/Git
surface which remains available in the normal bridge. A host must explicitly
create the server with `terminal=True` before terminal tools are registered.
The standalone entrypoint keeps terminal access disabled by default.

```python
server = create_server(config, terminal=True)
```

The terminal boundary does not expose a generic shell or subprocess API. It
reuses the existing `tools.terminal` command policy and adds MCP-specific
controls:

- canonical `WorkspaceSandbox` containment for `cwd`;
- the existing executable allowlist;
- the existing shell-chaining, redirection, expansion, and code-evaluation
  argument restrictions;
- workspace-local `.venv\\Scripts` executable resolution;
- a mandatory positive timeout bounded to 120 seconds;
- a bounded response output of at most 512 KiB;
- relative workspace paths only in returned metadata;
- successful command results captured as structured exit code/output data;
- successful and non-zero-exit results sent to an optional audit sink;
- timeout exceptions are propagated rather than converted into a false success.

### Terminal execution control plane

Each accepted terminal execution is assigned an opaque `execution_id` and
immediately enters the ephemeral `active` control state. The boundary exposes:

- `terminal_execution_status(execution_id)` for point-in-time lifecycle state;
- `terminal_execution_history(limit?)` for a bounded recent execution view;
- `execution_id` in the MCP `terminal_execute` response so clients can correlate
  the command with subsequent status queries;
- `active`, `completed`, and `failed` lifecycle states;
- `exit_code`, `timed_out`, and `truncated` only when execution reached the
  corresponding completion path;
- `error_type` for exceptions without fabricating an exit code.

The control-plane registry is deliberately in-memory and bounded per query;
it is **not** a second durable audit store. When `WorkflowEventLog` and
`project_id` are configured, the canonical log remains the durable lifecycle
record and carries the same execution ID. Concurrent terminal executions get
independent IDs and state records.

For compatibility, the low-level `MCPTerminalCapabilityBoundary.execute()`
keeps its historical result shape by default. The MCP server requests the
extended response containing `execution_id`; direct callers can opt into the
same field with `include_execution_id=True`.

The underlying terminal runner accepts an injected `WorkspaceSandbox` and a
subprocess timeout. Existing callers retain the legacy behavior when those
optional arguments are omitted, so this hardening does not change the existing
DeveloperAgent terminal contract.

Terminal capability deliberately does **not** provide:

- arbitrary executables;
- PowerShell code evaluation or encoded commands;
- shell chaining, redirection, or environment expansion;
- arbitrary host filesystem paths;
- direct `.git` metadata access;
- network APIs;
- subprocess handles;
- cancellation handles.

Output is truncated only at the MCP boundary, with an explicit truncation
marker. This keeps the MCP response bounded while retaining the exit code.
Timeout and output limits are independently validated before command execution.

## Public MCP surface

Workspace tools:

- `workspace_validate_path`
- `workspace_list_files`
- `workspace_read_file`
- `workspace_search_text`
- `workspace_write_file`
- `workspace_delete_file`

Git tools:

- `git_status`
- `git_diff`
- `git_log`
- `git_show`
- `git_branch`
- `git_rev_parse`
- `git_add`
- `git_commit`

Orchestration tools (only when a boundary is injected):

- `task_list`
- `task_get`
- `task_ready`
- `agent_list`
- `workflow_capabilities`
- `task_execution_history`
- `task_execution_status`
- `task_execute(task_id, idempotency_key?)`

Terminal tools (only when `terminal=True`):

- `terminal_execute(command, cwd?, timeout?, max_output_chars?)`
- `terminal_execution_status(execution_id)`
- `terminal_execution_history(limit?)`

`bridge_health` reports Phase 7 and whether terminal execution is actually
enabled. Terminal remains disabled by default, preventing an accidental
privilege expansion for existing MCP deployments.

## Security and compatibility rules

All workspace reads, mutations, Git operations, and terminal working
directories continue to cross the canonical `security.workspace.WorkspaceSandbox`.
Git operations continue through `HostGitOperationService` and the allow-listed
`tools.git.git_command` path. Terminal operations continue through the
allow-listed `tools.terminal` path. No MCP tool exposes a generic filesystem,
subprocess, Python object, environment variable, or network client.

Orchestration must use existing host-owned lifecycle and routing semantics.
The MCP layer must not mutate `Task.status`, task context, retry counters, or
agent registries directly.

Existing workflow event payload contracts must not be changed merely to add
MCP correlation. MCP-specific correlation is carried by its own adapter events
and the existing execution context. This preserves retry/replan compatibility.

The MCP bridge writes protocol traffic to stdout only through the MCP SDK;
operational logs remain on stderr. No direct `.git` metadata interface is
provided, and Git/terminal outputs are bounded before being returned to MCP
clients.
