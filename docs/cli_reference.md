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

Examples:

```powershell
python main.py "Build a small expense tracker"
python main.py "Build a small expense tracker" --projects-base F:\workspace\projects
python main.py "Build a small expense tracker" --dashboard runs\dashboard.html
python main.py "Build a small expense tracker" --output json
```

## JSON output

`--output json` is intended for scripts and CI consumers. The top-level object contains `result` and `tasks` fields. `result` is serialized through the canonical `ProjectResult.to_dict()` contract and includes project status/counts; each task entry contains stable task identity, status, role, title, and error fields.

Do not parse the human-readable output as a machine API. Use JSON mode when another program needs the result.

## Exit status

- `0` — command completed successfully.
- non-zero — command failed or could not complete the requested workflow.

The CLI does not expose secrets through either output mode. Runtime security boundaries remain authoritative for workspace and tool access.

## Troubleshooting

If the command fails during model configuration, validate the environment with the configuration checks described in `docs/configuration_reference.md`. For workflow/runtime failures, consult `docs/operational_troubleshooting.md`.
