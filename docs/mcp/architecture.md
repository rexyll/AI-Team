# AI-Team Local MCP Bridge Architecture — Phase 5

## Purpose

The bridge exposes a deliberately narrow MCP surface over an authorized local
AI-Team repository. It is an adapter, not a second runtime/security system.

```text
MCP Host
   |
   v
mcp_bridge
   |
   +-- configuration
   +-- read adapter policy
   +-- mutation adapter policy
   +-- Git capability policy
   |
   +------------------------------+
   |                              |
   v                              v
MCPWorkspaceBoundary      MCPWorkspaceMutationBoundary
   |                              |
   +--------------+---------------+
                  |
                  v
security.workspace.WorkspaceSandbox
                  |
                  v
          authorized workspace
                  |
                  v
       HostGitOperationService
```

Git operations cross the host-owned Git boundary rather than reading or
executing commands against `.git` directly.

## Phase 5 public MCP surface

The bridge exposes fifteen tools:

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

Workspace reads remain bounded and deterministic. Workspace mutations are
explicitly separated from the generic `tools.filesystem` implementation.
Git operations are explicitly separated from both workspace adapters.

## Workspace mutation policy

All workspace mutations cross `MCPWorkspaceMutationBoundary`, which delegates
path containment to `MCPWorkspaceBoundary` and therefore to the canonical
`security.workspace.WorkspaceSandbox`.

The mutation adapter additionally:

- rejects `.git`, `.venv`, caches, and IDE metadata;
- rejects paths outside the authorized workspace;
- accepts UTF-8 text only;
- enforces a configurable per-write byte limit capped at 8 MiB;
- creates parent directories only after validating the canonical parent path;
- refuses to overwrite an existing file unless `overwrite=true` is explicit;
- allows deletion only for regular files;
- returns relative paths only; and
- emits an audit event only after a successful mutation.

The adapter never invokes a shell, Git command, network request, or generic
filesystem tool.

## Git capability policy

`MCPGitCapabilityBoundary` is the only MCP entry point for Git operations. It
wraps `HostGitOperationService`, which in turn uses the allow-listed
`tools.git.git_command` execution primitive.

The exposed operation set is deliberately limited to:

- read: `status`, `diff`, `log`, `show`, `branch`, `rev-parse`;
- write: `add`, `commit`.

The following controls are enforced:

- every Git working directory is resolved through the MCP workspace sandbox;
- the working directory must be inside a Git repository and inside the
  authorized workspace;
- Git command execution uses `shell=False` and the existing command/option
  allowlist;
- dangerous repository redirection options such as `--git-dir`, `--work-tree`,
  `-C`, `--upload-pack`, and `--receive-pack` remain blocked;
- revisions cannot begin with `-` or contain shell metacharacters/newlines;
- commit messages are non-empty and single-line;
- `git add` paths are individually resolved and constrained to the authorized
  workspace;
- Git output is bounded before it crosses the MCP boundary; and
- `.git` is not exposed as a direct workspace metadata interface.

The host Git service can receive an explicit `WorkspaceSandbox`, so an MCP
server configured for a temporary or project-specific workspace does not fall
back to the process-wide default workspace boundary.

Git mutation auditing is currently kept at the host/server logging boundary.
A later production phase can route structured Git events into the canonical
runtime audit/tracing pipeline without widening Git authorization.

## Audit and tracing boundary

`WorkspaceMutationEvent` is the host-owned mutation event contract. The
mutation boundary accepts an audit sink callback and emits `create`, `update`,
or `delete` events only after the corresponding filesystem operation succeeds.

The MCP server also logs successful mutations through the existing stderr-only
application logger. The event payload contains only the relative path,
operation, and byte count; no host absolute path or file contents are emitted.

## Error behavior

The MCP SDK may normalize server-side exceptions into a generic tool error at
the protocol boundary. Security and validation behavior therefore remains
asserted at the boundary unit level, while MCP client contract tests assert
`is_error=true` for rejected operations.

## stdio safety

The MCP protocol uses stdout for stdio transport. Application logging is
therefore configured on stderr only.

## Capability roadmap

Phase 5 intentionally stops before terminal execution and network access.
Those capabilities require independent authorization, bounded execution,
timeouts, result limits, and audit semantics; they must not be added by
loosening the Git or workspace boundaries.

The next phase should focus on exposing host-owned AI-Team task/agent/workflow
operations through a separate MCP orchestration boundary, with read-only
inspection first and explicit mutation controls rather than exposing arbitrary
runtime internals.
