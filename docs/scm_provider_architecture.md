# SCM / Pull Request / CI Provider

## Provider boundary

`runtime/scm_provider.py` defines the provider-neutral `SCMProvider` contract and `SCMService` host boundary. The service exposes branch push, PR create/update, CI status, review status and merge. Provider credentials stay inside the provider implementation and are never passed to Agents.

`runtime/github_scm_provider.py` implements the GitHub REST adapter. `GitHubRESTTransport` requires a host-injected token and uses HTTPS, repository-scoped endpoints, a fixed API version and sanitized errors. It rejects all HTTP redirects rather than allowing urllib to forward the host Bearer token to another origin. Provider contract tests inject a fake transport; the redirect protection also has a real loopback-only HTTP integration test and never contacts GitHub.

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

Push, PR create/update and merge each require an `SCMApproval` issued by the host-owned `SCMApprovalAuthority`. An approval is scoped to one repository, operation and exact write target, expires within at most one hour, and is consumed once. A push target includes both the branch and exact local HEAD SHA; the provider rechecks HEAD and pushes that immutable SHA rather than mutable `HEAD`. A PR create/update target binds head branch, base branch, the exact expected pushed commit SHA, and a SHA-256 digest over that source SHA plus the canonical title/body payload. The host derives that SHA from the same one-use-approved push result; the digest therefore becomes invalid if the source commit, branch/base, title or body changes. A merge target binds PR number, exact head SHA, base branch and selected merge method. The interactive merge preview displays head, base and method; the publication preview displays the exact source SHA and an approval digest covering source SHA, branch/base, title and body. Immediately before the GitHub merge request, after the service-level one-use approval and preflight, the adapter re-reads the complete Check Runs + combined statuses and requires successful, complete CI; re-reads paginated Reviews and requires a complete approved review set anchored to the expected head; then re-reads PR metadata and requires open/unmerged/non-draft state plus the exact expected head and base before issuing PUT. The request also sends the expected head SHA, which GitHub checks atomically. PR create/update has a separate limitation: GitHub's PR API accepts a mutable branch name and exposes no atomic expected-head-SHA precondition. The provider binds host approval to the exact pushed SHA, checks the remote ref before and after lookup, and verifies the POST/PATCH response; nevertheless, a concurrent push can occur between the final ref read and write. A response mismatch is surfaced as failure and never retried automatically, but the PR may already have been created/updated; the host must re-read state and obtain a new approval before retrying. GitHub's merge API does not expose atomic expected-base-ref, CI-status, or review-state preconditions, so these final rechecks narrow but cannot eliminate the race between the last read and the merge request. Repositories must configure branch protection/rulesets to require the relevant status checks and review policy for server-side enforcement; adapter preflight alone cannot guarantee that a status or approval change in the final network interval will be rejected. A scope mismatch or replay is rejected. The authority is not exposed through Agent tools; application code must issue an approval only after explicit human authorization. Every remote write approval is consumed before the provider call. A missing, malformed, mismatched or lost write response is reported as failure and is never retried automatically; because the remote may already have accepted the write before the response failed, this is an indeterminate outcome rather than proof that no mutation occurred. The host must re-read the remote branch/PR state and obtain a new, target-specific approval before attempting another write.

The merge path performs deterministic preflight before consuming the merge approval:

- the PR must be open, unmerged, and explicitly non-draft;
- the PR head SHA, base branch and selected merge method must match the one-use approval scope;
- all check-run pages and combined commit statuses must resolve to `success` (incomplete pagination is not success);
- all review pages are read before re-reading PR metadata to anchor the complete review set to the current head SHA and PR author; only non-author reviews whose `commit_id` equals that head are considered, and each such reviewer's latest submitted state is used; a latest current-head `changes_requested` state blocks, incomplete bounded reads and unknown current-head review states remain pending, and malformed review entries reject the evidence rather than being silently discarded;
- only then may the host call the GitHub merge endpoint using `merge`, `squash` or `rebase`. The provider response must confirm the exact PR number and approved head SHA and include a valid resulting merge SHA; SCMService independently validates this response before reporting `merged`.

CI/review reads do not require write approval. The provider-neutral SCMService independently treats positive provider results as untrusted: CI success is downgraded to unknown unless checks_complete is exactly true; review approved is downgraded to pending unless reviews_complete is exactly true and a valid reviewed_head_sha is supplied. When an expected PR head is provided, the service additionally requires that anchor to match it. The merge service gate repeats the completeness and current-head requirements before consuming the one-use approval; the GitHub adapter repeats them again at the final write boundary. Missing, pending or unknown CI evidence is not treated as success. Check runs and reviews are paginated with a bounded page limit; reaching the limit without a final page fails closed rather than reporting readiness. Completed Check Run conclusions `action_required`, `cancelled`, `failure`, `stale`, `startup_failure` and `timed_out` map to CI failure; unrecognized conclusions or malformed entries map to unknown/pending. GitHub's combined commit-status API can return `pending` with an empty `statuses` array even when all Check Runs completed successfully; in that specific case the complete Check Run set is authoritative. If no Check Runs and no legacy status contexts exist, CI remains pending. Review readiness is commit-scoped: the provider reads PR head and author after review pagination, ignores reviews attached to older commits and ignores the PR author's own review. It returns `reviewed_head_sha`; the host service compares this anchor with the same head SHA used for CI before reporting `approved`, so CI and review evidence cannot be combined across different PR revisions. This adapter verifies at least one non-author approval on the current head; it does not fetch branch-protection rules or prove that a reviewer satisfies repository-specific required-reviewer/CODEOWNERS policy. GitHub's merge endpoint remains the final enforcement point for configured branch protection. Review aggregation also follows the latest submitted state per reviewer on the current head: every non-`PENDING` state must carry a parseable timezone-aware `submitted_at`; an unsubmitted `PENDING` review may omit that field but cannot supersede a submitted decision. Timestamps are parsed and compared as instants rather than lexicographic strings, so a later `COMMENTED` or `DISMISSED` state invalidates an earlier `APPROVED` state. Malformed, missing, or timezone-naive timestamps fail closed.

## Git push boundary

Git push is implemented by `HostGitOperationService`, not the Agent-visible `git_command` parser. Before a write, the host runs `git remote get-url --push --all origin` and requires exactly one effective push destination; this detects separate `pushurl` values and push-only URL rewrites rather than accidentally validating only the fetch URL. The destination must be the approved `owner/repository` using either the canonical `https://github.com/owner/repository[.git]` URL (no embedded userinfo, non-standard port, query, fragment, repeated separators or trailing path) or the standard `git@github.com:owner/repository.git` SSH form. The Host service rejects `url.*.insteadOf` and `url.*.pushInsteadOf` rewrite rules from every effective Git config scope, including system, global, local, included and command/environment configuration, then re-resolves the effective push URL after local HEAD verification and requires an exact match with the provider-approved destination. The final `git push` receives that literal URL instead of the mutable remote name `origin`, so changed `remote.origin.pushurl` or mirror settings cannot silently redirect the operation after the final destination check. Before repository discovery, the host rejects Git repository-context overrides (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, namespaces, index/object directories, shallow/discovery and exec-path controls), so these cannot redirect the local object or ref view. Before transport, the host rejects every `GIT_CONFIG` / `GIT_CONFIG_*` environment override, including command-scope injection (`GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_n`, `GIT_CONFIG_VALUE_n`, `GIT_CONFIG_PARAMETERS`) and alternate global/system config paths (`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM`), then rejects `credential.helper` and URL-specific `credential.*.helper` values from both repository-local and worktree Git configuration; it also rejects repository/worktree `include` and `includeIf` directives, which could inject an executable helper indirectly. Host-level credential helpers remain available, but a checked-out repository cannot provide its own executable credential program. Real local Git integration tests exercise ordinary and URL-scoped local helpers, conditional includes and worktree-scoped helpers against actual `.git` configuration files, with no remote transport. The fixed push argv disables local `pre-push` hooks, tag-following and submodule recursion, fixes the remote receive-pack command, and pins `GIT_SSH_COMMAND` to host-owned OpenSSH (overriding repository-local `core.sshCommand`) with non-interactive `BatchMode`. It pushes only the exact approved SHA to the requested branch with a non-force refspec. Multiple push destinations, mirror mode, arbitrary remotes and unsafe branch names cannot expand the write. A HostGitOperationService integration test uses a real local bare repository to verify that only the approved SHA reaches the explicit target ref; it is deliberately scoped to local Git transport and is not counted as live GitHub authentication, PR, review or merge evidence. The provider must confirm `status=pushed`, the exact repository and branch, and the exact approved `head_sha`; SCMService independently validates all four fields and returns only the canonical target-bound result. A provider's generic success flag cannot substitute for proof of which remote ref was updated. Git credentials come from the host's Git credential configuration.

## Host PR lifecycle coordinator

`runtime/scm_lifecycle.py` adds a host-callable lifecycle coordinator. It
requires two distinct, one-use approvals: one scoped to the exact local HEAD
and target branch for push, and another scoped to the PR head/base, the exact
SHA returned by the approved push, and a SHA-256 digest covering that source
SHA plus the exact title/body payload for PR creation or update. The coordinator
does not issue approvals and must only be called after an explicit operator
authorization flow. Push completes before the PR write is attempted; the host
passes the confirmed push SHA into the PR approval and provider call. The
provider reads the remote branch ref before the open-PR lookup and again
immediately before POST/PATCH; an existing open PR must match head ref, head
SHA and base ref. The write response must confirm the same PR head ref/SHA and
base ref, and SCMService independently validates the provider's created/updated
status, positive PR number, exact head branch, exact base branch and head SHA
before reporting success. A PR write failure
does not trigger a hidden retry; the pushed branch remains available for a
fresh read and a new PR approval.

The coordinator can poll PR metadata, CI and review evidence for a bounded
number of attempts (1–120) with a bounded interval (0–300 seconds). It returns
one of `ready`, `ci_failed`, `changes_requested`, `closed`, or `timeout`,
including the exact observed head SHA and CI/review states. It never retries a
failed CI job, edits a review, pushes additional commits, or merges. A caller
may use the structured failure evidence to prepare a proposed repair task, but
any repair, push, PR update, or merge remains a separate approved action.
Merge continues to use `SCMService.merge_pull_request`, which re-reads the
head/base, requires green CI and approved review, and consumes an approval
scoped to the PR number, exact head SHA, base branch and merge method.

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
workflow definition, GitHub SCM adapter, host SCM service, or read-only probe
script changes on `main`; its path filter prevents unrelated application
pushes from repeatedly probing a historical PR. It defaults to PR #2
(the repository's existing stale draft),
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
repository, branch, base, PR title, exact PR source SHA and a digest
covering source SHA + title/body. The operator must type `yes` at two
separate prompts: first to approve pushing that exact SHA, then to approve
creating/updating a PR for that same commit and displayed payload. Any other
response cancels before the corresponding write. The host issues two separate
one-use approvals scoped to the push (branch + exact SHA) and PR (head branch,
base branch, expected pushed SHA and canonical title/body digest). The provider
checks the remote branch SHA before and after open-PR lookup, validates an
existing PR's head/base identity, and validates the POST/PATCH response against
the approved source SHA and target branches. This narrows but cannot eliminate
the race between the final remote-ref read and the GitHub PR write API, which
has no atomic expected-head-SHA parameter; any post-write response mismatch is
reported as failure without automatic retry. The command is standalone and
cannot be combined with a normal delivery invocation.

Read-only PR polling needs read access to pull requests, checks and commit
statuses. Publication additionally requires write access to contents (git push)
and pull requests (create/update); merge uses pull-request write access. Restrict
credentials to the disposable target repository. A fine-grained PAT can cover
contents, pull requests and commit statuses but does not currently support the
Checks API, so it cannot provide the complete CI evidence required by this
adapter. For full lifecycle acceptance, prefer a GitHub App installation token
with only Contents read/write, Pull requests read/write, Checks read and Commit
statuses read, installed only on the test repository. Never broaden the
credential or expose its value to the interactive prompt, Agent, task context
or logs. Merge remains a separate operation requiring a distinct approval
after green CI and approved review.



PR create/update also fails closed on malformed or ambiguous lookup responses. The provider only creates a PR after an explicit empty array from the open-PR query; a non-array response, malformed entry, invalid number, or multiple matches produces an error and no POST/PATCH write.

PR publication displays a SHA-256 digest over the exact head, base, title and body payload.
The one-use PR approval is bound to that digest as well as head/base; changing
the title or body after confirmation invalidates the approval. The body remains
in the host process and is not copied into Agent context.


PR create/update fails closed on malformed or ambiguous open-PR
lookup responses: only an explicit empty array permits a new PR POST. A
non-array response, malformed entry, multiple matching PRs, invalid number or
mismatched update response aborts without falling through to create a new PR.

## Interactive merge approval

A PR can be merged through the standalone host command:

```bash
python main.py --scm-merge-pr 123 --scm-merge-method squash
```

The command first polls the PR and proceeds only when it is open, unmerged,
non-draft, CI is green and the latest review is approved. It displays the exact
head SHA, base branch and selected merge method, and requires a real interactive
TTY plus an explicit `yes`. The host then issues a one-use merge approval scoped to
`PR-number:head-SHA:base-branch:merge-method` and calls
`SCMService.merge_pull_request`.
That service independently re-reads PR metadata, verifies open/unmerged,
non-draft state and the exact head/base/method approval scope, and rechecks
CI and review. Immediately before the merge PUT, the GitHub adapter re-reads the PR
again and checks the head and base still match; the PUT sends the expected head
SHA, which GitHub checks atomically. GitHub's merge API has no atomic expected
base-ref parameter, so a narrow base-ref race remains between the final read
and the PUT. A blocked PR never prompts for or receives a merge approval.
Cancellation and non-TTY execution perform no merge write. JSON output remains
machine-readable; human prompts and previews go to stderr.

## Lifecycle integration test contract

`tests/test_scm_lifecycle_e2e.py` exercises the host service and lifecycle
coordinator together with one deterministic provider fixture. The happy path
asserts the observable operation order:

1. Read the local HEAD and push only that approved SHA.
2. Create/update the PR only after the push succeeds.
3. Poll PR metadata, CI and review without performing writes.
4. Re-read PR metadata and CI/review immediately before merge; verify exact
   head SHA, base branch, open/unmerged and non-draft state.
5. Send the exact observed head SHA as GitHub's conditional merge SHA; the
   base branch is rechecked immediately before the request.

Failure fixtures cover CI failure/pending timeout, changes requested, closed
or draft PRs, local HEAD drift before push, PR head/base drift after polling,
PR closure after polling, head/base/state drift immediately before the GitHub
merge PUT, PR creation API failure and merge API failure. These tests
assert that blocked paths do not issue later writes and that provider failures
are propagated rather than silently retried.

Publication is a two-step remote saga, not an atomic GitHub transaction: if
the push succeeds but PR creation fails, the branch remains pushed. The CLI
reports the error and does not retry or roll back the push automatically.
The operator can inspect the remote branch and explicitly retry PR creation
with a new approval. Likewise, a merge API timeout may have an ambiguous
remote outcome; callers must re-read PR state before attempting another merge.

## Current validation boundary

The provider protocol, one-use approval lifecycle, preflight and GitHub REST request/response behavior have mock contract tests. The live read-only path was exercised against PR #2 on 2026-11-16 by workflow runs #2, #3 and #4. The run-scoped repository `GITHUB_TOKEN` had only contents/pull-requests/checks/statuses read permission. Run #4 returned `ok=true`, `assessment=blocked`, `draft=true`, base branch `refactor/runtime-architecture`, pending commit status, zero check runs, pending review and zero reviews; `checks_complete=true` and `reviews_complete=true`. This is the expected negative sample and verifies live PR head/state/base, CI and review reads; it does not prove a green/approved ready path. Run #5 additionally probed a known completed main commit (`4d5604a54d21c7389d0c5d93079b31aba958c698`): GitHub returned four completed successful Check Runs but a synthetic combined commit status of `pending` with an empty `statuses` list. The adapter correctly returned `ci_aggregation_probe.status=success` with `checks_complete=true`, proving successful Checks are not masked by an empty legacy-status collection. The probe is pinned through `AI_TEAM_GITHUB_CI_PROBE_SHA` and remains read-only. The code path is covered by `tests/test_github_scm_provider.py`; the live smoke fails if the configured probe does not aggregate to success. No push, PR write, review mutation or merge was performed. Live write-path validation still requires an isolated test repository and explicit one-use host approvals.



## Isolated live write-path runbook

Use a disposable private repository dedicated to SCM adapter acceptance; do not use
`rexyll/AI-Team` or another project repository as the write target. The test
repository should have a default base branch (for example `main`) and no valuable
content. Keep the clone, branch, remote, token and PR entirely scoped to that
repository.

For a complete read/write test, use a GitHub App installation access token
installed only on the disposable repository. The adapter calls the Checks API,
which fine-grained personal access tokens do not currently support; an App
installation token can grant the narrower per-repository permissions needed:
`Contents: read/write` (Git push), `Pull requests: read/write` (PR
create/update/merge and reviews), `Checks: read` (Check Runs), and
`Commit statuses: read` (combined status). `Metadata: read` is implicit.
Keep the installation token short-lived. The host's Git credential helper must
also be configured to authenticate the sandbox clone's HTTPS push using that
installation token; `AI_TEAM_GITHUB_TOKEN` is used by the REST adapter and is
not automatically copied into Git's credential store. Never place a token in
the remote URL, a command-line argument, a PR body or chat. GitHub documents
the permissions and the Checks API fine-grained-token limitation here:
[GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app),
[GitHub App endpoint permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps),
[Fine-grained PAT limitations](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

Configure the host environment without echoing the secret:

```bash
export AI_TEAM_GITHUB_REPOSITORY="OWNER/ai-team-scm-sandbox"
export AI_TEAM_GITHUB_TOKEN="$(cat /secure/path/to/short-lived-installation-token)"
unset AI_TEAM_GITHUB_PULL_REQUEST
```

Clone the sandbox, configure the host Git credential helper for the same
repository-scoped installation token, then create and commit a harmless test
file on a dedicated test branch. Verify `git remote get-url origin` names only
the sandbox repository before invoking the CLI. The publish command itself
rechecks that origin and the exact local HEAD SHA:

```bash
python main.py --scm-publish-pr \
  --scm-local-repository /path/to/ai-team-scm-sandbox \
  --scm-head-branch ai-team/scm-live-test \
  --scm-base-branch main \
  --scm-pr-title "AI-Team SCM live acceptance" \
  --scm-pr-body-file /path/to/scm-live-test-pr-body.md
```

Review both displayed confirmations carefully: the first authorizes pushing the
displayed exact HEAD SHA; the second independently authorizes creating/updating
the PR. Record the returned PR number. Wait for the sandbox's CI checks to
finish, then obtain an approval from a separate authorized reviewer account.
Only after the following read-only command returns `ready` should the merge
command be considered:

```bash
python main.py --scm-poll-pr PR_NUMBER
python main.py --scm-merge-pr PR_NUMBER --scm-merge-method squash
```

The merge command displays the PR head SHA and base branch and requires a
separate interactive `yes`. The adapter re-reads the PR immediately before
merge; GitHub atomically checks the expected head SHA, while the base-ref check
is a pre-write recheck because the merge API has no atomic expected-base-ref
parameter. Capture the CLI output and resulting PR state as acceptance evidence.
After the test, revoke/remove the installation access as appropriate and
delete the disposable repository only after preserving the evidence. Never
paste the installation token into this repository's issues, PRs, logs or chat.
