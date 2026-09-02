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
   +-- MCPPolicy
   |     +-- workspace write
   |     +-- Git write
   |     +-- workflow execute
   |     +-- terminal capability
   |
   +-- MCPOperationTracker
   |     +-- request_id
   |     +-- operation_id
   |     +-- execution_id
   |     +-- duration / outcome / error category
   |
   +-- workspace / Git / terminal adapters
   +-- MCPOrchestrationBoundary
   |
   v
host-owned runtime + WorkflowEventLog
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
records `mcp_task_execution_requested` and a matching completed/failed event in
the existing canonical `WorkflowEventLog`. Execution status and history are
projections of that log. An optional `idempotency_key` is atomically bound to a
single task execution and fails closed when canonical execution observability
is unavailable.

## Phase 7 controlled terminal boundary

Terminal access is an **optional host capability**, unlike the read/write/Git
surface which remains available in the normal bridge. A host must explicitly
create the server with `terminal=True` before terminal tools are registered.
The standalone entrypoint keeps terminal access disabled by default.

The Phase 7.4 policy layer now adds a second, process-level gate: terminal
registration requires both explicit host opt-in (`terminal=True`) and a policy
profile that allows terminal execution. The same policy gates workspace
mutation, Git write operations, and workflow execution, so a deployment can
reduce the MCP surface without changing the underlying canonical boundaries.

Supported profiles are:

- `developer` — preserves the existing Phase 7 capability set; terminal is
  available only when the host explicitly passes `terminal=True`.
- `readonly` — read-only workspace/Git/task inspection; workspace mutation,
  Git writes, terminal execution, and workflow execution are not registered.
- `production` — fail-closed read-only deployment profile; workspace mutation,
  Git writes, terminal execution, and workflow execution are disabled even if a
  host explicitly requests terminal access.

The profile is configured with `AI_TEAM_MCP_POLICY_PROFILE`. The compatibility
`create_server(config)` path still defaults to `developer`, but the standalone
entrypoint uses `readonly` when no profile is explicitly configured. Therefore
running the bridge directly cannot silently acquire mutation or execution
privileges. A deployment that needs developer capabilities must explicitly set
the policy profile to `developer`; production deployments should explicitly
select `production`.

## Startup and transport security

The standalone bridge accepts only `stdio` transport. `AI_TEAM_MCP_TRANSPORT`
is validated at startup and currently permits only the explicit value `stdio`.
Unknown or future network transports fail configuration rather than being
silently accepted. Adding HTTP, SSE, or another network transport requires a
separate security-reviewed implementation and authentication/origin policy.

Startup configuration is treated as the security boundary:

- `AI_TEAM_WORKSPACE` is mandatory and must be an absolute existing directory;
- the standalone default policy is `readonly`;
- terminal remains disabled unless both the host requests it and policy allows
  it (and the standalone entrypoint does not request it);
- policy capabilities are used for registration rather than inferred from
  command-line arguments or transport selection;
- `bridge_health` reports the effective policy and actual transport/capability
  state;
- operational logs remain on stderr so MCP protocol traffic is not mixed with
  diagnostics.

This prevents startup configuration from creating a second privilege path
around `MCPPolicy`.

```text
standalone startup
      |
      +--> validated workspace
      +--> validated stdio transport
      +--> readonly default policy
      |
      v
MCPPolicy --> actual registered tools --> bridge_health
```

## MCP operation identity, observability, and errors

All server-registered MCP capability calls are wrapped by a single
`MCPOperationTracker`. Each invocation receives an opaque `request_id` and
`operation_id`; execution-producing calls additionally correlate their
returned `execution_id`. The tracker records policy profile, capability,
start/finish timestamps, duration, outcome, and a stable error category.

The tracker is deliberately bounded and in-memory. It is a correlation and
metrics adapter, **not** a durable audit store. Durable workflow lifecycle
remains owned by `WorkflowEventLog`, and terminal-specific lifecycle remains
owned by its existing control-plane boundary.

The MCP error contract normalizes failures into stable categories:

- `configuration_error`
- `policy_denied`
- `invalid_request`
- `execution_error`
- `not_found`
- `bridge_error`

The server records the normalized category for observability while preserving
the existing exception/result behavior of the underlying MCP tools. This
avoids creating a second incompatible error envelope at the protocol adapter
layer.

## Secret and environment isolation

MCP must not become an indirect environment-variable reader. Terminal and Git
child processes therefore receive a derived environment with credential-like
variables removed. Normal execution variables such as `PATH`, `TEMP`,
`SystemRoot`, and locale settings remain available so the existing developer
toolchain continues to work.

The environment filter blocks variables whose names indicate API keys,
tokens, authentication/authorization material, credentials, passwords,
secrets, private keys, or client/session/refresh secrets. MCP callers cannot
supply an arbitrary child-process environment through the public terminal or
Git capability APIs.

Tool output is also passed through the MCP redaction boundary. Known inherited
host secret values and common credential-bearing string patterns are redacted
before terminal/Git results are returned. Operation telemetry sanitizes
metadata and identity fields, and normalized MCP errors sanitize exception
messages. This is a defense-in-depth boundary; it does not claim that arbitrary
secrets stored in workspace files can be perfectly detected.

```text
MCP request
    |
    +--> policy/config validation
    |
    +--> operation tracker (sanitized telemetry)
    |
    +--> terminal/Git child process
    |       |
    |       +--> sanitized environment
    |
    +--> bounded + redacted result
    |
    v
MCP response
```

## Public MCP surface

The capability surface is policy-derived. Read tools remain available across
profiles; mutation and execution tools are registered only when the effective
policy allows them. `bridge_health` exposes the same effective policy and
transport values used during registration.

Workspace tools:

- `workspace_validate_path`
- `workspace_list_files`
- `workspace_read_file`
- `workspace_search_text`
- `workspace_write_file` (developer policy)
- `workspace_delete_file` (developer policy)

Git tools:

- `git_status`
- `git_diff`
- `git_log`
- `git_show`
- `git_branch`
- `git_rev_parse`
- `git_add` (developer policy)
- `git_commit` (developer policy)

Orchestration tools (only when a boundary is injected):

- `task_list`
- `task_get`
- `task_ready`
- `agent_list`
- `workflow_capabilities`
- `task_execution_history`
- `task_execution_status`
- `task_execute(task_id, idempotency_key?)` (developer policy)

Terminal tools (only when `terminal=True` **and** policy allows terminal):

- `terminal_execute(command, cwd?, timeout?, max_output_chars?)`
- `terminal_execution_status(execution_id)`
- `terminal_execution_history(limit?)`

`bridge_health` reports the active policy profile, transport, and whether
terminal execution is actually enabled.

## Security and compatibility rules

All workspace reads, mutations, Git operations, and terminal working
directories continue to cross the canonical `security.workspace.WorkspaceSandbox`.
Git operations continue through `HostGitOperationService` and the allow-listed
`tools.git.git_command` path. Terminal operations continue through the
allow-listed `tools.terminal` path. No MCP tool exposes a generic filesystem,
subprocess, Python object, environment variable, or network client.

The policy layer only decides whether a capability is exposed. It does not
weaken or replace domain-level authorization, path containment, command
allowlisting, Git restrictions, or workflow lifecycle ownership.

Orchestration must use existing host-owned lifecycle and routing semantics.
The MCP layer must not mutate `Task.status`, task context, retry counters, or
agent registries directly.

Existing workflow event payload contracts must not be changed merely to add
MCP correlation. MCP-specific correlation is carried by its own adapter events
and the existing execution context. This preserves retry/replan compatibility.

The MCP bridge writes protocol traffic to stdout only through the MCP SDK;
operational logs remain on stderr. No direct `.git` metadata interface is
provided, and Git/terminal outputs are bounded and sanitized before being
returned to MCP clients.
