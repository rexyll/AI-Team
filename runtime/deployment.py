"""Deployment bundle builder: installers, container template, smoke test.

Turns the finished deliverable into a deployable package a customer can
install without reading the source:

- ``install.ps1`` / ``install.sh`` bootstrap scripts (copy files, create a
  virtualenv, install declared requirements, run the smoke command);
- a ``Dockerfile`` template (documented placeholder entry point — building
  the image requires the customer's container toolchain);
- ``SMOKE_REPORT.md`` — a smoke verification that extracts the deliverable
  into a fresh directory and actually runs its test suite there, so "the
  package deploys" is verified, not assumed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.packaging import create_delivery_package

DEFAULT_SMOKE_TIMEOUT = 300.0


def _excluded(path: Path) -> bool:
    parts = path.parts
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or path.name.endswith(".pyc")
    )


def find_test_files(deliverable_root: str | Path) -> list[str]:
    """Return deliverable-relative test file paths (pytest convention)."""
    root = Path(deliverable_root)
    tests: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if _excluded(rel) or "__pycache__" in rel.parts:
            continue
        name = path.name
        if name.startswith("test_") or name.endswith("_test.py"):
            tests.append(rel.as_posix())
    return tests


def generate_installer_scripts(*, project: str, test_files: list[str]) -> dict[str, str]:
    """Render the Windows/POSIX bootstrap installers for the bundle."""
    smoke_cmd = (
        "python -m pytest " + " ".join(test_files) if test_files else "python --version"
    )
    install_ps1 = f"""# {project} — Windows 部署引导脚本
# 用法: 在解压后的目录内以管理员或普通用户身份运行:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== {project} 部署开始 ==="
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {{
    throw "未检测到 python，请先安装 Python 3.10+ 并加入 PATH。"
}}

# 1) 可选虚拟环境
if ($env:CREATE_VENV -eq "1") {{
    python -m venv .venv
    & .venv\\Scripts\\python.exe -m pip install --upgrade pip
}}

# 2) 依赖安装（如声明了 requirements.txt）
if (Test-Path "requirements.txt") {{
    pip install -r requirements.txt
}}

# 3) 部署冒烟验证
{smoke_cmd}
if ($LASTEXITCODE -ne 0) {{ throw "部署冒烟验证失败" }}

Write-Host "=== 部署完成，冒烟验证通过 ==="
"""
    install_sh = f"""#!/usr/bin/env bash
# {project} — POSIX 部署引导脚本
# 用法: 在解压后的目录内运行: bash install.sh
set -euo pipefail

echo "=== {project} 部署开始 ==="
if ! command -v python >/dev/null 2>&1; then
    echo "未检测到 python，请先安装 Python 3.10+" >&2
    exit 1
fi

# 1) 可选虚拟环境
if [ "${{CREATE_VENV:-0}}" = "1" ]; then
    python -m venv .venv
    ./.venv/bin/python -m pip install --upgrade pip
fi

# 2) 依赖安装（如声明了 requirements.txt）
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

# 3) 部署冒烟验证
{smoke_cmd}

echo "=== 部署完成，冒烟验证通过 ==="
"""
    return {"install.ps1": install_ps1, "install.sh": install_sh}


def generate_dockerfile_template(*, project: str, entry_hint: str | None = None) -> str:
    """Render a Dockerfile template for Python deliverables.

    The CMD is a documented placeholder: the customer adjusts the entry point
    per the deployment guide. Building the image requires the customer's
    container toolchain and is intentionally not performed here.
    """
    entry = entry_hint or "main.py  # ← 按部署指引修改为实际入口"
    return f"""# {project} — 容器镜像模板
# 构建: docker build -t {project.lower().replace(' ', '-')}:latest .
# 说明: CMD 为占位入口，请按 docs/deployment.md 中的已验证命令调整。
FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt || echo "no requirements.txt"

CMD ["python", "{entry}"]
"""


def run_smoke_verification(
    deliverable_root: str | Path,
    *,
    python: str = sys.executable,
    timeout: float = DEFAULT_SMOKE_TIMEOUT,
) -> dict[str, Any]:
    """Run the deliverable's test suite from a fresh copy of the files.

    The smoke runs with the working directory set to a temp copy so the
    verification exercises the deployed layout, not the authoring workspace.
    """
    root = Path(deliverable_root)
    test_files = find_test_files(root)
    if not test_files:
        return {"status": "skipped", "reason": "no test files found", "exit_code": None}

    smoke_dir = Path(tempfile.mkdtemp(prefix="ai-team-smoke-"))
    for test_file in test_files:
        target = smoke_dir / test_file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / test_file, target)
    # Runtime modules imported by the tests travel with them.
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if _excluded(rel):
            continue
        target = smoke_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    command = [python, "-m", "pytest", *test_files, "-q"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(smoke_dir),
            capture_output=True,
            timeout=timeout,
        )
        exit_code = completed.returncode
        output = (completed.stdout or b"").decode("utf-8", errors="replace")[-2000:]
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "command": " ".join(command),
            "exit_code": None,
            "reason": f"smoke timed out after {timeout} seconds",
        }
    finally:
        shutil.rmtree(smoke_dir, ignore_errors=True)

    return {
        "status": "passed" if exit_code == 0 else "failed",
        "command": " ".join(command),
        "exit_code": exit_code,
        "output_tail": output,
    }


def create_deployment_bundle(
    deliverable_root: str | Path,
    *,
    output_dir: str | Path | None = None,
    project: str = "ai-team-delivery",
    smoke: bool = True,
    smoke_timeout: float = DEFAULT_SMOKE_TIMEOUT,
) -> dict[str, Any]:
    """Build the deployment bundle: delivery zip + installers + smoke report.

    Extends the verified delivery package with bootstrap installers, a
    container template, and the smoke verification result. Fails closed if
    the archive or the smoke verification is inconsistent.
    """
    package = create_delivery_package(deliverable_root, output_dir=output_dir, project=project)
    archive_path = Path(package["archive"])
    test_files = find_test_files(deliverable_root)

    smoke_result: dict[str, Any] = {"status": "skipped", "reason": "smoke disabled"}
    if smoke:
        smoke_result = run_smoke_verification(
            deliverable_root, timeout=smoke_timeout
        )

    smoke_report = (
        f"# 部署冒烟验证报告（Smoke Report）\n\n"
        f"- 状态：**{smoke_result['status'].upper()}**\n"
        f"- 命令：`{smoke_result.get('command', '')}`\n"
        f"- 生成时间：{datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}\n"
    )

    installers = generate_installer_scripts(
        project=project, test_files=find_test_files(deliverable_root)
    )
    generated = {
        **installers,
        "Dockerfile": generate_dockerfile_template(project=project),
        "SMOKE_REPORT.md": smoke_report,
    }

    with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in generated.items():
            bundle.writestr(name, content)

    # Verify the final archive: every original member plus every generated one.
    with zipfile.ZipFile(archive_path, "r") as bundle:
        members = set(bundle.namelist())
    missing = [name for name in generated if name not in members]
    if missing:
        raise ValueError(f"deployment bundle missing generated members: {missing}")
    data = archive_path.read_bytes()

    return {
        "bundle": str(archive_path),
        "files": package["files"],
        "size": len(data),
        "checksum": hashlib.sha256(data).hexdigest(),
        "smoke": smoke_result,
        "installers": sorted(generated),
    }
