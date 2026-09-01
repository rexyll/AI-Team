from __future__ import annotations

import subprocess

from tools import run_production_readiness as readiness


def test_readiness_gates_are_ordered_and_use_real_regression_contracts() -> None:
    names = [name for name, _ in readiness.GATES]
    assert names == [
        "security",
        "extension-boundary",
        "observability",
        "persistence-recovery",
        "full-regression",
    ]

    commands = dict(readiness.GATES)
    assert commands["security"][-1] == "tools/run_security_regression.py"
    assert commands["extension-boundary"][-4:] == (
        "tests/test_plugin_api.py",
        "tests/test_plugin_extension_compatibility.py",
        "tests/test_extension_examples_contract.py",
        "-q",
    )
    assert commands["observability"][:3] == (readiness.sys.executable, "-m", "pytest")
    assert "tests/test_tracing.py" in commands["observability"]
    assert "tests/test_workflow_event_metrics.py" in commands["observability"]
    assert "tests/test_workflow_recovery_state_consistency.py" in commands["persistence-recovery"]
    assert commands["full-regression"][-2:] == ("pytest", "-q")


def test_main_fails_fast_when_a_gate_fails(monkeypatch, capsys) -> None:
    calls: list[tuple[tuple[str, ...], str]] = []

    def fake_run(command, *, cwd, check):
        calls.append((tuple(command), str(cwd)))
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)

    code = readiness.main()

    assert code == 7
    assert len(calls) == 1
    assert "gate_failed=security exit_code=7" in capsys.readouterr().err


def test_main_runs_all_gates_when_they_pass(monkeypatch, capsys) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command, *, cwd, check):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)

    assert readiness.main() == 0
    assert len(calls) == len(readiness.GATES)
    assert "production_readiness=passed" in capsys.readouterr().out
