# SCM / Pull Request / CI Provider

## Provider boundary

`runtime/scm_provider.py` defines the provider-neutral `SCMProvider` contract and `SCMService` host boundary. The service exposes branch push, PR create/update, CI status, review status and merge. Provider credentials stay inside the provider implementation and are never passed to Agents.

`runtime/github_scm_provider.py` implements the GitHub REST adapter. `GitHubRESTTransport` requires a host-injected token and uses HTTPS, repository-scoped endpoints, a fixed API version and sanitized errors. Tests inject a fake transport; they do not contact GitHub.

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
