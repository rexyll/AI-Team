# CLI Reference

The primary entry point is `main.py` from the repository root.

## Usage

```powershell
python main.py "<project requirement>"
```

### Options

- `--projects-base <path>` — select the sandbox/projects base directory.
- `--dashboard <path>` — export the operational dashboard HTML after execution.
- `--output text|json` — select human-readable or machine-readable output. The default is `text`.
- `--release` — run the release phase after a successful delivery (semver
  version, `RELEASE_NOTES.md`, deliverable git anchor, `release_log.json`).
- `--release-version <semver>` — pin the release version; otherwise it
  auto-bumps the deliverable's last recorded version.
- `--auto-release` — skip the release confirmation prompt (implies `--release`).
- `--milestone <name>` — record a milestone label for a single delivery in
  `RELEASE_NOTES.md` and `release_log.json`.
- `--requirements-file <path>` — deliver a milestone release plan (see below).
- `--release-plan-output <path>` — where the shared plan document is written
  (default `release_plan.md`).
- `--release-history [path]` — read-only: aggregate every `release_log.json`
  under `path` (default: projects base) and print the version history, then exit.
- `--knowledge-base <path>` — enable the cross-project knowledge base (a
  `.json` file or a directory). Matching historical patterns/pitfalls/
  conventions are loaded into the analyst and doc-writer context; lessons from
  this delivery are extracted into the store afterwards (see below).
- `--knowledge-query <text>` — keyword filter for loading knowledge assets;
  also applies to `--knowledge-list`.
- `--knowledge-list [path]` — read-only: list stored knowledge assets
  (default `knowledge/`), then exit.
- `--knowledge-extract <path>` — read-only: backfill knowledge from an existing
  deliverable directory (`release_log.json` and
  `docs/acceptance_report.md`) into `--knowledge-base` (default `knowledge/`),
  then exit.
- `--monitor-check <path>` — run the delivered post-delivery heartbeat (release
  anchor, manifest SHA-256 integrity, regression suite), write
  `monitoring/status.json`, then exit. Exits non-zero unless the status is
  `healthy`; `--output json` prints the full report.
- `--deployment-history <path>` — opt in to host-owned deployment history.
  It can also be configured with `AI_TEAM_DEPLOYMENT_HISTORY`; when set, the
  CLI runs a read-only unfinished-replacement inventory on every process start.
- `--deployment-recovery-inventory` — standalone read-only inventory report
  (supports `--output json`); requires `--deployment-history` or the
  `AI_TEAM_DEPLOYMENT_HISTORY` environment variable.
- `--hotfix-project <path>` — existing released deliverable to hotfix. Requires
  `--defect-intake`; runs hotfix tasks through integration regression, QA, the
  security audit, the release gate, a patch release and repackaging on the same
  deliverable.
- `--defect-intake <path>` — UTF-8 Markdown defect list for
  `--hotfix-project`.
- `--hotfix-version <semver>` — optional explicit hotfix version (defaults to a
  patch bump of the last release).

`--hotfix-project` is a standalone defect-reflow run: it cannot be combined with
a positional requirement, `--requirements-file`, `--change-request`,
`--clarifications`, `--milestone`, `--release-version` or a read-only mode.

Examples:

```powershell
python main.py "Build a small expense tracker"
python main.py "Build a small expense tracker" --projects-base F:\workspace\projects
python main.py "Build a small expense tracker" --dashboard runs\dashboard.html
python main.py "Build a small expense tracker" --output json
python main.py "Build a small expense tracker" --release --auto-release
```

```powershell
# host startup inventory (the same check runs on every CLI startup while configured)
$env:AI_TEAM_DEPLOYMENT_HISTORY = "C:\\AI-Team-Host\\deployments.sqlite3"
python main.py "Build a small expense tracker"

# standalone read-only inventory
python main.py --deployment-recovery-inventory --output json
```

## Milestone release plans

`--requirements-file` accepts a UTF-8 Markdown plan. `## 里程碑 ...` starts a
milestone and `### 需求 ...` starts one requirement; the body under the
requirement heading is the requirement text handed to the analyst. An optional
`[vX.Y.Z]` suffix pins that delivery's release version:

```markdown
# 发布计划：记账工具分期交付

## 里程碑 M1：基础可用
### 需求 R1：记账核心 [v0.1.0]
开发一个命令行记账工具，支持添加与列表。

### 需求 R2：账单统计
增加月度汇总输出，所有文件放在 workspace/ledger 目录下。

## 里程碑 M2：增强
### 需求 R3：导出
支持导出 CSV。
```

Each requirement runs as a complete, sequential delivery (analysis → tasks →
tests → integration → packaging → release) with its own version. A failed
requirement stops the batch; remaining requirements are recorded as `skipped`
and the shared plan document (`--release-plan-output`) records every outcome
(status, acceptance verdict, version/tag, deliverable root, error). The command
exits non-zero when any requirement did not complete.

Options that do not apply to a plan (`--release-version`, `--milestone`,
`--clarifications`, `--change-request`, `--interactive`, `--resume-session`,
`--analyze-only`, or the positional requirement) are rejected.

## Release history

```powershell
python main.py --release-history
python main.py --release-history F:\workspace\projects --output json
```

The command walks the base directory (bounded depth, hidden/runtime-cache
directories pruned), reads every `release_log.json`, and prints the merged
version list. A corrupt log fails closed instead of silently dropping releases.

## Cross-project knowledge base

`--knowledge-base` turns finished deliveries into reusable assets. The store is
a single JSON file (a directory path resolves to
`<dir>/knowledge_base.json`) with entries of three kinds:

- **pattern (模式)** — a delivery approach that worked, e.g. the green baseline
  (acceptance / integration / static / QA all passing on the first round).
- **pitfall (坑)** — concrete failure evidence: acceptance gaps and warnings,
  integration failure or rework rounds, static-gate failures, `QA_FAILED`
  verdicts, unpinned or undeclared dependencies.
- **convention (规范)** — a practice worth repeating, e.g. fully pinned
  dependency declarations or semver + git tag + `release_log.json` release
  anchors.

Extraction is deterministic: entries are derived by fixed rules from the
delivery record (or, for `--knowledge-extract`, from a deliverable's
`release_log.json` and `docs/acceptance_report.md`). Entry identity is a hash of
(project, kind, title), so re-extracting the same delivery or re-running the
same project deduplicates instead of growing the store. Entries carry tags,
target roles and a timestamp; loading is filtered by role/kind/keyword and
bounded to the most relevant assets, which are fenced as untrusted historical
data in the prompt.

```powershell
# deliver with knowledge reuse; new lessons are written back after delivery
python main.py "Build a small expense tracker" --knowledge-base knowledge

# inspect the store (text or --output json)
python main.py --knowledge-list knowledge

# filter by keyword while listing or loading
python main.py --knowledge-list knowledge --knowledge-query 依赖

# backfill lessons from an already finished deliverable
python main.py --knowledge-extract F:\workspace\projects\ledger --knowledge-base knowledge
```

A corrupt knowledge file fails closed; a failure to write new lessons during a
delivery is recorded in `delivery.knowledge` and never invalidates the finished
product.

## Post-delivery monitoring and defect reflow

Every delivery writes `monitoring/health_contract.json` and `MONITORING.md`
after the release (before the manifest, so both are checksummed and packaged).
The contract declares only offline-verifiable probes and states that no cloud
APM/alerting channel is integrated:

```powershell
# heartbeat (cron/Task Scheduler friendly: non-zero exit = alert)
python main.py --monitor-check F:\workspace\projects\ledger
python main.py --monitor-check F:\workspace\projects\ledger --output json
```

Customer defects use a strict Markdown intake; `## 缺陷 DEF-001 标题` starts a
defect, `严重级别` and `描述` are required, `影响版本` / `复现步骤` are optional:

```markdown
## 缺陷 DEF-001 登录后立即退出
- 严重级别: 严重
- 影响版本: v0.1.0
- 描述: 输入正确凭据后进程退出。
- 复现步骤: 运行 login 命令，输入 admin/admin。
```

```powershell
# hotfix: defects -> fix/verify tasks -> integration regression -> patch release -> repackage
python main.py --hotfix-project F:\workspace\projects\ledger --defect-intake defects.md --auto-release
```

The flow requires a released baseline (`release_log.json`), rejects duplicate
ids, unknown fields, invalid severities and affected versions absent from the
release history, and writes `docs/defect_report.md` (`FIXED` / `PENDING` /
`FAILED`) plus `hotfix_request.md` (`CHG-xxx`, usable with `--change-request`).


## Incremental revision of a persisted project

`--revise-project PATH` revises an existing project snapshot (`<project_id>.json`
written by `ProjectPersistenceAdapter`) after a customer change request. The
original requirement is passed as the positional argument so the analyst can
produce the amended specification; the workspace anchoring matches a normal
delivery (`--projects-base` applies).

```powershell
python main.py "Build a small expense tracker" --revise-project F:\workspace\projects\snapshots\PROJECT-001.json --change-request change.md
python main.py "Build a small expense tracker" --revise-project F:\workspace\projects\snapshots\PROJECT-001.json --change-request change.md --output json
```

Contract:

- `--revise-project` requires `--change-request` and the positional requirement;
  it is a standalone revision mode and cannot be combined with `--interactive`,
  `--resume-session`, `--analyze-only`, `--requirements-file`, `--hotfix-project`
  or the read-only inspection flags.
- The change request goes through the regular authoritative analyst channel
  (`customer.change_request` fence, `CHG-xxx` amendments) and the delivery is
  re-planned.
- Impact analysis is deterministic and LLM-free: old and new tasks are matched
  by plan id, then by normalised title (same role). A completed task is reused
  only when its title, description and id-mapped dependencies are unchanged;
  changed tasks and their transitive downstream are reset, unmatched tasks are
  new work, removed tasks are dropped from the graph and listed in the report.
- Only affected/pending tasks execute; the delivery phase (integration
  regression, QA, security audit, documents, acceptance, release go/no-go,
  monitoring/deployment readiness, manifest and packaging when requested) runs
  again as the gate for the revised product.
- The snapshot is updated in place (atomic writes, checkpointed at execution
  boundaries). No match at all degrades honestly to a full re-run; the report
  then shows `mode: "full"`.
- `--output json` adds a top-level `revision` object: `mode`, `reused`,
  `affected`, `added`, `carried`, `removed`, `removed_completed`,
  `reset_completed`, `match_bases`, `project_id`, `chars`.

## JSON output

`--output json` is intended for scripts and CI consumers. The top-level object contains `result` and `tasks` fields. `result` is serialized through the canonical `ProjectResult.to_dict()` contract and includes project status/counts; each task entry contains stable task identity, status, role, title, and error fields.

Do not parse the human-readable output as a machine API. Use JSON mode when another program needs the result.

## Exit status

- `0` — command completed successfully.
- non-zero — command failed or could not complete the requested workflow.

The CLI does not expose secrets through either output mode. Runtime security boundaries remain authoritative for workspace and tool access.

## Troubleshooting

If the command fails during model configuration, validate the environment with the configuration checks described in `docs/configuration_reference.md`. For workflow/runtime failures, consult `docs/operational_troubleshooting.md`.
