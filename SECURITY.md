# AI-Team Security Regression

AI-Team treats security controls as runtime boundaries, not prompt-level conventions. The security regression suite covers the currently implemented dependency, network-egress, secret-isolation, prompt-injection, workspace/tool-permission, and evidence/provenance boundaries.

## Run the security suite

From the repository root:

```powershell
python tools/run_security_regression.py
```

The runner discovers security regression modules by their security-related test filename patterns and invokes pytest with the repository's active Python interpreter. A non-zero pytest exit code is propagated to the caller.

For the complete regression suite, continue to use:

```powershell
pytest -q
```

## Security boundary expectations

- **Dependency policy:** runtime dependencies are explicitly declared, exactly pinned, and not duplicated.
- **Network egress:** network operations are deny-by-default and must pass the HTTPS/hostname authorization boundary before the underlying operation runs.
- **Secret isolation:** secrets are redacted before crossing agent-context, tool-record, durable-result, and audit boundaries.
- **Prompt injection:** task data, dependency output, tool results, repository content, test output, and agent feedback are untrusted data. They cannot change runtime authorization or tool permissions.
- **Workspace/tool boundary:** filesystem and command operations enforce the runtime workspace and capability policy independently of model output.
- **Evidence gate:** stage authorization is fail-closed and requires explicit provenance; compatibility handling must not weaken the generic validator.

## Maintenance rule

When a new security boundary is introduced, add focused regression coverage and ensure its test filename matches one of the discovery patterns in `tools/run_security_regression.py`, or extend that runner as part of the same change.
