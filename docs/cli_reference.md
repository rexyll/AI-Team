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

Examples:

```powershell
python main.py "Build a small expense tracker"
python main.py "Build a small expense tracker" --projects-base F:\workspace\projects
python main.py "Build a small expense tracker" --dashboard runs\dashboard.html
python main.py "Build a small expense tracker" --output json
python main.py "Build a small expense tracker" --release --auto-release
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

## JSON output

`--output json` is intended for scripts and CI consumers. The top-level object contains `result` and `tasks` fields. `result` is serialized through the canonical `ProjectResult.to_dict()` contract and includes project status/counts; each task entry contains stable task identity, status, role, title, and error fields.

Do not parse the human-readable output as a machine API. Use JSON mode when another program needs the result.

## Exit status

- `0` — command completed successfully.
- non-zero — command failed or could not complete the requested workflow.

The CLI does not expose secrets through either output mode. Runtime security boundaries remain authoritative for workspace and tool access.

## Troubleshooting

If the command fails during model configuration, validate the environment with the configuration checks described in `docs/configuration_reference.md`. For workflow/runtime failures, consult `docs/operational_troubleshooting.md`.
