# Phase 19.4 — Git / CI / PR collaboration

Status: host-owned Git operation boundary implemented; local focused and full regression validation remains the acceptance gate.

## Implemented

- Added `runtime.host_git.HostGitOperationService` as the host-owned Git boundary.
- Added immutable `GitOperationRequest` with a fixed semantic operation vocabulary:
  `status`, `diff`, `log`, `show`, `branch`, `rev-parse`, `add`, and `commit`.
- The host service validates the workspace through `WorkspaceSandbox` and verifies that the selected directory belongs to a Git repository before executing an operation.
- Relative `git add` paths are anchored to the selected repository workspace and cannot escape the authorized sandbox.
- Revision arguments reject option-style injection and shell metacharacters.
- Commit messages are required to be non-empty and single-line.
- Raw `git_command` was removed from `TOOLS_SCHEMA` and the default `ToolRegistry`, so it is no longer an agent/plugin-visible tool.
- `git_command` remains available as a low-level compatibility helper for host-owned code and existing direct security tests.
- `RuntimeCapabilityPolicy` marks `git_command` as `HOST_ONLY_TOOLS`; agent roles cannot authorize or filter it into their tool surface.
- Quoted Git arguments are normalized correctly by the low-level helper so the host semantic boundary can safely handle paths and commit messages containing spaces.

## Architectural boundary

```text
Agent / Plugin
    X raw git_command
    |
    | host-owned request only
    v
HostGitOperationService
    -> WorkspaceSandbox
    -> repository validation
    -> fixed semantic Git operation
    -> low-level git subprocess helper
```

The host boundary deliberately does not expose `push`, arbitrary Git subcommands, `--git-dir`, `--work-tree`, `-C`, config injection, or shell execution.

## Scope of this increment

This increment establishes the Git operation boundary only. CI status interpretation and PR lifecycle operations remain separate host-owned collaboration capabilities and must not be implemented by widening the raw Git command surface.

## Regression coverage

`tests/test_host_git.py` covers:

- semantic operation surface without an arbitrary command field;
- raw Git removal from the agent registry;
- host-only capability enforcement for every agent role;
- repository validation and host-owned status execution;
- workspace-relative `git add` path handling;
- workspace escape rejection;
- commit-message validation;
- revision option-injection rejection.

Existing `tests/test_security_tools.py` continues to cover the low-level Git helper's workspace and shell/subcommand guards.

## Acceptance

Run locally:

```powershell
pytest tests/test_host_git.py tests/test_security_tools.py -q
pytest -q
```

Only after the focused and full suites pass should this increment be treated as accepted.
