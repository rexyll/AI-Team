# AI-Team Production Configuration Checklist

This checklist documents the configuration facts a deployment must satisfy before running the AI-Team runtime outside of the contract-test environment. Every item reflects verifiable repository state; when the runtime changes, this checklist and its contract test (`tests/test_production_configuration_contract.py`) must change in the same DevPlan node.

## 1. Runtime prerequisites

- Windows 11 with **Python 3.14**.
  - Python 3.14 is a hard requirement: `tools/registry.py` relies on PEP 649 lazy annotation evaluation. On Python <= 3.13, importing `tools.registry` (and therefore any `agents.*` chain) fails at import time with `TypeError: 'function' object is not subscriptable`.
  - The project is a source tree, not an installed wheel. Run commands from the repository root so `core.*`, `runtime.*`, `agents.*` imports resolve.

## 2. Declared dependencies

Install from the repository root:

```powershell
pip install -r requirements.txt
```

`requirements.txt` pins the versions validated by the local development environment:

- `openai==3.1.0`
- `python-dotenv==1.2.3`

These are required because `config/model.py` imports both packages unconditionally. Contract tests themselves stay network-independent through mock injection (see §3).

## 3. Provider configuration (environment variables)

`config/model.py` reads the following variables (a `.env` file at the repository root is honored through `load_dotenv()`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AGNES_API_KEY` | yes | — | API key for the OpenAI-compatible provider |
| `AGNES_BASE_URL` | no | `https://apihub.agnes-ai.com/v1` | Provider base URL |
| `AGNES_MODEL` | no | `agnes-2.5-flash` | Model identifier passed to chat calls |

**Import-time behavior warning:** `config/model.py` validates `AGNES_API_KEY` and eagerly constructs the OpenAI client during module import. Any import chain that reaches it (`import agents.base`, `runtime.llm.provider`, or running `main.py` in provider mode) raises immediately when the key is missing. Configure the environment before importing agent modules; do not treat this as a lazy failure.

## 4. Network-free execution (mock mode)

For local verification without provider access, inject `MockLLM` (`runtime/llm/mock.py`) through the agent constructor's `llm=` parameter, exactly as the contract tests do. `BaseAgent(llm=None)` defaults to `ProviderLLM()`, which uses the eager client from §3. Mock mode never touches the network and produces deterministic responses.

## 5. Workspace sandbox

- The default authorized workspace is the project root: `security/workspace.DEFAULT_SANDBOX = WorkspaceSandbox(PROJECT_ROOT)`.
- A custom root can be set per deployment by constructing `WorkspaceSandbox(root)` explicitly instead of relying on the default instance.
- Permission policy is deny-by-default; path-escape, shell-expansion, and git-transport protections are enforced by `tests/test_security_contract.py`. Production deployments must not bypass these layers.

## 6. Persistence storage requirements

- `WorkflowEventPersistenceAdapter(root)` and `ProjectPersistenceAdapter(root)` publish writes atomically via temporary files plus `os.replace()` inside the target directory.
- Storage roots therefore must live on a filesystem that supports atomic rename within a directory (local NTFS/ext4). Network shares are unvalidated for this guarantee.
- Event stores are immutable and append-only (`save_if_absent`); project snapshots use `save`/`update`/`checkpoint` semantics with identity validation on load.
- Failure boundaries (batch publication failure, temp-file cleanup, recovery after failure) are covered by `tests/test_failure_injection_contract.py` and the Phase 8.6 contention contracts.

## 7. Operational read-only guarantees

Query, projection, and audit entry points (`WorkflowEventQueryService`, `WorkflowEventProjector`, `ToolExecutionAudit`, `ProjectPersistenceAdapter.audit*`) are read-only by contract. They must not write to stores or mutate runtime state; concurrent-read safety under append load is covered by the Phase 8.6 concurrency contracts.

## 8. Pre-deployment verification

Run from the repository root:

```powershell
pytest -q
python examples/persistence_recovery.py
python main.py "Build a small personal expense tracker"
```

The full `pytest -q` run is the acceptance gate for every DevPlan node. The example verifies durable recovery semantics end to end; the CLI run verifies the configured provider path executes one real project workflow.
