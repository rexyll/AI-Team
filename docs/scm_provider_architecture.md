# SCM / Pull Request / CI Provider

## Provider boundary

`runtime/scm_provider.py` defines the provider-neutral `SCMProvider` contract and `SCMService` host boundary. The service exposes branch push, PR create/update, CI status, review status and merge. Provider credentials stay inside the provider implementation and are never passed to Agents.

`runtime/github_scm_provider.py` implements the GitHub REST adapter. `GitHubRESTTransport` requires a host-injected token and uses HTTPS, repository-scoped endpoints, a fixed API version and sanitized errors. Tests inject a fake transport; they do not contact GitHub.

## Project orchestration integration

`runtime.ProjectOrchestrator` accepts an optional host-created `SCMService` together with an explicit repository and pull-request number. When configured, the delivery phase performs read-only observation after product integration verification and records the PR head SHA, PR state, CI result and latest review result in the delivery task context as `scm_observation`.

This observation is informational and fail-closed: only an open, unmerged PR with successful CI and an approved review is labeled `ready`; pending/unknown/failing evidence is `blocked`; transport/provider exceptions are recorded as `unavailable` with the exception type only. It never creates a branch, pushes, creates/updates a PR or merges. SCM configuration is opt-in, so projects without it retain their existing behavior. Write operations remain explicit host actions requiring one-use approvals.

## Host credential configuration

The CLI creates the GitHub SCM runtime only when all three host environment
variables are present:

- `AI_TEAM_GITHUB_TOKEN`: a fine-grained GitHub token supplied by the host.
- `AI_TEAM_GITHUB_REPOSITORY`: the explicit `owner/name` repository.
- `AI_TEAM_GITHUB_PULL_REQUEST`: a positive pull-request number.

No variables means SCM observation is disabled and existing delivery behavior
is preserved. A partial repository/PR pair or a missing token fails closed with
a configuration error. The token is injected directly into
`GitHubRESTTransport`; it is not a CLI argument, ProjectOrchestrator argument,
Agent tool, task-context field, or serialized runtime field. Do not place it in
source control, requirement text, command-line arguments, or project documents.
Use the host's secret manager/environment injection and grant only the minimum
repository permissions required for read-only PR/check/review observation.
Write operations remain unavailable to Agents and still require a separate
one-use host approval through `SCMService`.

The factory is `runtime/github_scm_config.py:create_github_scm_runtime`.
It validates repository and PR configuration before constructing a provider.
Invalid/expired credentials or insufficient permissions surface as unavailable
SCM evidence; they are never interpreted as a successful check. GitHub error
details are sanitized to prevent an echoed credential from appearing in errors.

## Write approval

Push, PR create/update and merge each require an `SCMApproval` issued by the host-owned `SCMApprovalAuthority`. An approval is scoped to one repository, operation and target, expires within at most one hour, and is consumed once. A push target includes both the branch and exact local HEAD SHA; the provider rechecks HEAD and pushes that immutable SHA rather than mutable `HEAD`. A merge approval is additionally bound to the exact PR head SHA observed during preflight, so branch movement after approval invalidates the approval. The GitHub merge request also sends that expected SHA in the API body, letting GitHub reject a head change between preflight and merge (TOCTOU protection). A scope mismatch or replay is rejected. The authority is not exposed through Agent tools; application code must issue an approval only after explicit human authorization.

The merge path performs deterministic preflight before consuming the merge approval:

- the PR head SHA must be available;
- commit checks and combined commit statuses must resolve to `success`;
- the latest review state must resolve to `approved` (a latest `changes_requested` state blocks);
- only then may the host call the GitHub merge endpoint using `merge`, `squash` or `rebase`.

CI/review reads do not require write approval. Missing, pending or unknown CI evidence is not treated as success.

## Git push boundary

Git push is implemented by `HostGitOperationService`, not the Agent-visible `git_command` parser. The host verifies that `origin` resolves to the approved `owner/repository`, and pushes `HEAD` to the requested branch with a fixed, non-force refspec. Force-push, arbitrary remotes and unsafe branch names are rejected. Git credentials come from the host's Git credential configuration.

## Current validation boundary

The provider protocol, one-use approval lifecycle, preflight and GitHub REST request/response behavior have mock contract tests. No live GitHub push, PR creation, CI read, review read or merge has been performed in this environment; that requires a host-configured GitHub token, a test repository and explicit operator approval. The implementation must not be described as live-integrated until that run is completed.
