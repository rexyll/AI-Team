# Production Readiness Evidence

## Phase 18.5 acceptance run

The production readiness gate was executed locally from the repository root with:

```powershell
python tools/run_production_readiness.py
```

The gate completed successfully with all five stages passing.

| Gate | Result |
| --- | ---: |
| Security regression | 207 passed |
| Extension boundary | 28 passed |
| Observability | 78 passed |
| Persistence / recovery | 17 passed |
| Full regression | 1909 passed |

Final gate result:

```text
production_readiness=passed
```

## Boundary evidence

The production readiness run includes the security and extension-boundary suites that protect the following runtime invariants:

- capability and permission authorization remains host-owned;
- prompt-injection handling remains isolated from runtime authorization;
- workspace and filesystem boundaries remain enforced;
- Host-owned Git operations are not exposed through the Agent-visible `ToolRegistry`;
- observability records remain correlated without leaking raw secret or inspected prompt-injection content;
- workflow recovery and persistence projections remain covered by focused contracts;
- the complete regression suite remains green after the production-readiness changes.

## Performance acceptance note

Phase 18.3 remains correctness-first. The available real-Developer A/B evidence does not establish a clear efficiency gain, and the upstream OpenAI-compatible tool-continuation compatibility issue remains unresolved for the real provider path. Synthetic continuation prompts must not be treated as a performance fix because prior live evidence showed that they can alter Developer trajectory and trigger progress-guard failures.

Therefore this evidence closes the Production Readiness gate only; it does not claim that Phase 18.3 performance optimization is complete.

## Acceptance rule

Future changes to runtime invocation, persistence/recovery, security, observability, extension boundaries, or Developer tool-loop behavior must rerun the production readiness gate before the Phase 18 acceptance decision is changed.
