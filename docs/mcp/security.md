# Local MCP Bridge Security — Phase 7

## Active controls

1. Explicit absolute workspace root; no implicit process cwd.
2. Canonical path resolution through `WorkspaceSandbox`.
3. Parent/absolute/symlink workspace escapes rejected.
4. Direct `.git` metadata access denied.
5. Workspace reads and writes remain bounded and policy-controlled.
6. Git operations remain allow-listed through the host Git service.
7. Terminal execution is disabled by default and must be explicitly enabled by the host.
8. Terminal executables remain allow-listed; arbitrary shell commands are rejected.
9. Shell chaining, redirection, expansion, PowerShell code evaluation, and encoded-command arguments are rejected.
10. Terminal `cwd` is resolved through the canonical workspace sandbox.
11. Terminal execution has a positive timeout capped at 120 seconds.
12. Terminal MCP responses are bounded to 512 KiB and explicitly mark truncation.
13. Terminal execution returns an exit code and never turns a timeout into a false success.
14. Terminal successful/non-zero results can be sent to a host-provided audit sink.
15. No subprocess handle, generic filesystem handle, environment-variable access, or network client is exposed to MCP callers.
16. MCP application logs go to stderr, not the stdio protocol channel.
17. Orchestration uses the host-owned runtime and canonical `WorkflowEventLog`; MCP does not create a second audit store.
18. MCP execution idempotency fails closed when canonical execution observability is unavailable.

## Terminal threat model

The Phase 7 terminal capability is intended for bounded development commands such
as tests, builds, linters, and package tooling. It is not a general-purpose
shell.

The existing `tools.terminal` policy remains the source of truth for executable
and command validation. The MCP boundary adds scope, timeout, output, and audit
controls without bypassing that policy. Workspace-local virtual-environment
executable resolution is preserved so commands such as `pytest` continue to use
the project's `.venv` when available.

A terminal timeout raises `TimeoutError`. It is deliberately not represented as
an ordinary exit-code result because the underlying process may have been
terminated before producing a trustworthy command result. This fail-closed
behavior prevents callers from treating an interrupted command as successful.

## Deferred / future controls

The following are intentionally not claimed as complete by Phase 7:

- interactive terminal sessions or persistent subprocess handles
- MCP terminal cancellation handles
- network capability
- protected-branch Git policy
- durable terminal audit persistence beyond the host-provided sink
- operating-system-specific sandboxing beyond the existing workspace and command policy
- resource quotas beyond timeout and bounded MCP response size
- remote MCP authentication/authorization policy
