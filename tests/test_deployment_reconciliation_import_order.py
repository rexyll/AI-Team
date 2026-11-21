"""Regression coverage for reconciliation grant module import direction."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_MODULE_ORDERS = (
    (
        "runtime.deployment_reconciliation_authority",
        "runtime.deployment_reconciliation_grant_maintenance",
        "runtime.deployment_reconciliation_grant_vault",
        "runtime.deployment_host",
    ),
    (
        "runtime.deployment_reconciliation_grant_vault",
        "runtime.deployment_reconciliation_authority",
        "runtime.deployment_reconciliation_grant_maintenance",
        "runtime.deployment_host",
    ),
    (
        "runtime.deployment_reconciliation_grant_maintenance",
        "runtime.deployment_reconciliation_grant_vault",
        "runtime.deployment_reconciliation_authority",
        "runtime.deployment_host",
    ),
    (
        "runtime.deployment_host",
        "runtime.deployment_reconciliation_grant_vault",
        "runtime.deployment_reconciliation_grant_maintenance",
        "runtime.deployment_reconciliation_authority",
    ),
)


@pytest.mark.parametrize("module_order", _MODULE_ORDERS)
def test_reconciliation_grant_modules_import_without_order_sensitive_cycles(
    module_order: tuple[str, ...],
) -> None:
    root = Path(__file__).resolve().parents[1]
    script = "\n".join(f"import {module}" for module in module_order)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        f"module import order failed: {module_order}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
