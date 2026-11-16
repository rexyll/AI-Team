# SCM / Pull Request / CI Provider

## Provider boundary

`runtime/scm_provider.py` defines the provider-neutral `SCMProvider` contract and `SCMService` host boundary. The service exposes branch push, PR create/update, CI status, review status and merge. Provider credentials stay inside the provider implementation and are never passed to Agents.

`runtime/github_scm_provider.py` implements the GitHub REST adapter. `GitHubRESTTransport` requires a host-injected token and uses HTTPS, repository-scoped endpoints, a fixed API version and sanitized errors. Tests inject a fake transport; they do not contact GitHub.

## Project orchestration integration

`runtime.ProjectOrchestrator` accepts an optional host-created `SCMService` together with an explicit repository and pull-request number. When configured, the delivery phase performs read-only observation after product integration verification and records the PR head SHA, PR state, CI result and latest review result in the delivery task context as `scm_observation`.

This observation is informational and fail-closed: only an open, unmerged, non-draft PR with successful CI and an approved review is labeled `ready`; draft, pending/unknown/failing evidence is `blocked`; transport/provider exceptions are recorded as `unavailable` with the exception type only. It never creates a branch, pushes, creates/updates a PR or merges. SCM configuration is opt-in, so projects without it retain their existing behavior. Write operations remain explicit host actions requiring one-use approvals.

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

- the PR must be open, unmerged, and explicitly non-draft;
- the PR head SHA must be available;
- all check-run pages and combined commit statuses must resolve to `success` (incomplete pagination is not success);
- all review pages are read in chronological order before computing each reviewer's latest submitted state; a latest `changes_requested` state blocks, and an incomplete bounded read remains pending;
- only then may the host call the GitHub merge endpoint using `merge`, `squash` or `rebase`.

CI/review reads do not require write approval. Missing, pending or unknown CI evidence is not treated as success. Check runs and reviews are paginated with a bounded page limit; reaching the limit without a final page fails closed rather than reporting readiness.

## Git push boundary

Git push is implemented by `HostGitOperationService`, not the Agent-visible `git_command` parser. The host verifies that `origin` resolves to the approved `owner/repository`, and pushes `HEAD` to the requested branch with a fixed, non-force refspec. Force-push, arbitrary remotes and unsafe branch names are rejected. Git credentials come from the host's Git credential configuration.

## Host PR lifecycle coordinator

`runtime/scm_lifecycle.py` adds a host-callable lifecycle coordinator. It
requires two distinct, one-use approvals: one scoped to the exact local HEAD
and target branch for push, and another scoped to the head/base pair for PR
creation or update. The coordinator does not issue approvals and must only be
called after an explicit operator authorization flow. Push completes before
the PR write is attempted; if the PR write fails, the pushed branch remains
available for a safe retry after a new PR approval.

The coordinator can poll PR metadata, CI and review evidence for a bounded
number of attempts (1–120) with a bounded interval (0–300 seconds). It returns
one of `ready`, `ci_failed`, `changes_requested`, `closed`, or `timeout`,
including the exact observed head SHA and CI/review states. It never retries a
failed CI job, edits a review, pushes additional commits, or merges. A caller
may use the structured failure evidence to prepare a proposed repair task, but
any repair, push, PR update, or merge remains a separate approved action.
Merge continues to use `SCMService.merge_pull_request`, which re-reads the
head, requires green CI and approved review, and consumes an approval scoped
to that exact head SHA.

## Read-only CLI polling

The CLI exposes `--scm-poll-pr NUMBER` as a standalone read-only operation.
Set `AI_TEAM_GITHUB_TOKEN` and `AI_TEAM_GITHUB_REPOSITORY=owner/name` in the
host environment, then run:

```bash
python main.py --scm-poll-pr 123 --output json
```

The explicit PR number overrides `AI_TEAM_GITHUB_PULL_REQUEST` for this
invocation, so the environment need not pin a single PR. The command cannot be
combined with a delivery request or other operational command. It uses the
bounded lifecycle poller and emits the observed head SHA, CI state, review
state, attempt count and terminal status. Exit code 0 means `ready`; exit
code 2 means the PR is blocked, closed or timed out; exit code 1 means the
configuration/provider operation failed. The command performs no push, PR
write, review mutation or merge.

## CI failure to bounded repair-task proposal

After a delivery observes a failed CI status, the host re-reads the PR head and
CI result through `SCMService` before preparing a repair task. The factory
accepts only an open, unmerged PR whose current head has CI status `failure`.
Pending, unknown, successful, closed, or merged PR evidence does not create a
task.

A proposal is attached to the project task graph with status `blocked`, so it
cannot enter the ready queue. It records the PR identity, exact failed head SHA,
commit status, up to 100 check-run status records, capture time, and a SHA-256
digest. Check output summaries/log text are not copied into task context; the
structured status evidence is retained and fenced as untrusted data for the
developer. The evidence digest makes repeated polling idempotent.

The default limit is two repair rounds per repository/PR, with a hard maximum
configuration of five. An outstanding proposal blocks another proposal for
that PR; only after the previous task reaches a terminal state can another
round be created. Existing history must be contiguous and well-formed or the
factory fails closed. The proposal remains blocked until a host explicitly
approves it. This feature does not execute a developer, consume retry budget,
rerun CI, push commits, write PR metadata, alter reviews, or merge.

## Live read-only GitHub integration smoke

The workflow uses the repository-scoped `GITHUB_TOKEN` issued for that run,
with only `contents: read`, `pull-requests: read`, `checks: read`, and
`statuses: read` permissions. A narrow push trigger runs the probe when the
workflow definition itself changes on `main`; its path filter prevents ordinary
application pushes from repeatedly probing a historical PR. That one-shot
workflow-change run defaults to PR #2 (the repository's existing stale draft),
which is intentionally a negative/blocked sample for validating the live read
path. Operators can also use Actions → **SCM live read-only smoke** → Run
workflow and enter another existing pull-request number; the manual input
defaults to `2`. No schedule is configured.
It invokes `scripts.scm_live_readonly_smoke` through the same host configuration
factory and GitHub REST provider used by the CLI.

The probe reads PR state/head SHA, check runs, combined commit status, and review
state once. It emits a sanitized JSON record: check-run names/status/conclusions
and timestamps are retained, but provider output summaries and error messages
are not printed. `ok=true` means the live API observation succeeded;
`assessment=blocked` is a valid result when CI is not green or a review is not
approved. The workflow does not push, create/update PRs, change reviews, or merge.

This proves only the live read path. Push, PR write, and merge still require a
separate test repository, the host's explicit one-use approvals, and a dedicated
write-enabled validation; the read-only workflow cannot exercise those paths.

## Interactive host approval for publication

The CLI exposes a separate publication command:

```bash
python main.py --scm-publish-pr \
  --scm-local-repository /path/to/local/repository \
  --scm-head-branch feature/my-change \
  --scm-base-branch main \
  --scm-pr-title "Implement my change" \
  --scm-pr-body-file /path/to/pr-body.md
```

It requires `AI_TEAM_GITHUB_TOKEN` and
`AI_TEAM_GITHUB_REPOSITORY=owner/name`, but does not require a default PR
number. Before any remote write, it reads and displays the exact local HEAD SHA,
repository, branch, base and PR title. The operator must type `yes` at two
separate prompts: first to approve pushing that exact SHA, then to approve
creating/updating the PR. Any other response cancels before the corresponding
write. The host issues two separate one-use approvals scoped to the push
(branch + exact SHA) and PR head/base pair. The provider verifies that the
local HEAD has not changed and that `origin` points to the approved repository
before pushing. The command is standalone and cannot be combined with a normal
delivery invocation.

Read-only PR polling needs only the minimum read permissions for pull requests,
checks and commit statuses. Publication additionally requires GitHub repository
write permission for contents (git push) and pull requests (create/update).
Use a fine-grained token restricted to the target repository. Never broaden the
token or expose its value to the interactive prompt, Agent, task context or
logs. Merge remains a separate operation requiring a distinct approval after
green CI and approved review.

## Interactive merge approval

A PR can be merged through the standalone host command:

```bash
python main.py --scm-merge-pr 123 --scm-merge-method squash
```

The command first polls the PR and proceeds only when the PR is open and
unmerged, CI is green and the latest review is approved. It displays the exact
head SHA and requires a real interactive TTY plus an explicit `yes`. The host
then issues a one-use merge approval scoped to `PR-number:head-SHA` and calls
`SCMService.merge_pull_request`. That service independently re-reads the PR,
checks that it remains open/unmerged, rechecks CI and review, consumes the
approval only when all preflight checks pass, and sends the expected SHA to
GitHub to protect against branch movement. A blocked PR never prompts for or
receives a merge approval. Cancellation and non-TTY execution perform no merge
write. JSON output remains machine-readable; human prompts and previews go to
stderr.

## Lifecycle integration test contract

`tests/test_scm_lifecycle_e2e.py` exercises the host service and lifecycle
coordinator together with one deterministic provider fixture. The happy path
asserts the observable operation order:

1. Read the local HEAD and push only that approved SHA.
2. Create/update the PR only after the push succeeds.
3. Poll PR metadata, CI and review without performing writes.
4. Re-read PR metadata and CI/review immediately before merge.
5. Send the exact observed head SHA as GitHub's conditional merge SHA.

Failure fixtures cover CI failure/pending timeout, changes requested, closed
PRs, local HEAD drift before push, PR head drift after polling, PR closure
after polling, PR creation API failure and merge API failure. These tests
assert that blocked paths do not issue later writes and that provider failures
are propagated rather than silently retried.

Publication is a two-step remote saga, not an atomic GitHub transaction: if
the push succeeds but PR creation fails, the branch remains pushed. The CLI
reports the error and does not retry or roll back the push automatically.
The operator can inspect the remote branch and explicitly retry PR creation
with a new approval. Likewise, a merge API timeout may have an ambiguous
remote outcome; callers must re-read PR state before attempting another merge.

## Current validation boundary

The provider protocol, one-use approval lifecycle, preflight and GitHub REST request/response behavior have mock contract tests. The live read-only path was also exercised on 2026-11-16 by push-triggered workflow run #2 against PR #2. Using the run-scoped repository `GITHUB_TOKEN` with only contents/pull-requests/checks/statuses read permission, the adapter returned `ok=true` and `assessment=blocked`; the PR was open/unmerged at head `85abdaf906607a2240ebc6bb69b61d0d5b735455`, commit status was pending with no check runs, and review status was pending with zero reviews. This is the expected negative sample and proves the live read-only adapter path; it does not prove a green/approved ready path. No push, PR write, review mutation or merge was performed. Live write-path validation still requires an isolated test repository and explicit one-use host approvals.
