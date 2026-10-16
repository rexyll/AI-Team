"""Host-controlled, offline static checks for Python delivery artifacts."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

_EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _run(name: str, arguments: list[str], cwd: Path, timeout: float) -> dict:
    if importlib.util.find_spec(name) is None:
        return {"name": name, "status": "unavailable", "exit_code": None, "output": "Tool is not installed in the host environment"}
    command = [sys.executable, "-I", "-m", name, *arguments]
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE",
    }}
    try:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            output.seek(0)
            text = output.read(16384).decode("utf-8", errors="replace")
        status = "passed" if completed.returncode == 0 else "failed" if completed.returncode == 1 else "error"
        return {"name": name, "status": status, "exit_code": completed.returncode, "output": text}
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "timeout", "exit_code": None, "output": "Static check exceeded its time limit"}
    except OSError:
        return {"name": name, "status": "error", "exit_code": None, "output": "Unable to start static check"}


def run_static_gate(deliverable_root: str | Path, *, timeout: float = 120) -> dict:
    """Check a source-only snapshot without importing customer modules or plugins.

    Dependency vulnerability auditing is deliberately not a network side effect
    of this offline gate. A dependency-bearing product remains unverified until
    a separately authorized dependency audit is supplied.
    """
    if not 0 < timeout <= 600:
        raise ValueError("timeout must be within (0, 600]")
    root = Path(deliverable_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("deliverable_root must be a directory")
    checks = []
    with tempfile.TemporaryDirectory(prefix="ai-team-static-") as directory:
        snapshot = Path(directory)
        files = []
        dependencies = False
        total_bytes = 0
        for folder, dirs, names in os.walk(root, followlinks=False):
            base = Path(folder)
            dirs[:] = [d for d in dirs if d not in _EXCLUDED and not (base / d).is_symlink() and not (base / d).is_junction()]
            for name in sorted(names):
                source = base / name
                if source.is_symlink() or not source.resolve().is_relative_to(root):
                    raise ValueError("Delivery source must not escape its root")
                if name in {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "uv.lock"} or (
                    name.startswith("requirements") and name.endswith(".txt")
                ):
                    dependencies = True
                if source.suffix != ".py":
                    continue
                total_bytes += source.stat().st_size
                if len(files) >= 10000 or total_bytes > 50 * 1024 * 1024:
                    raise ValueError("Static source snapshot exceeds size limit")
                target = snapshot / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                files.append(target.relative_to(snapshot).as_posix())
        if files:
            checks.append(_run("ruff", ["check", "--isolated", "--no-cache", "--select", "E9,F", "."], snapshot, timeout))
            config = snapshot / "host-mypy.ini"
            config.write_text("[mypy]\n", encoding="utf-8")
            checks.append(_run("mypy", ["--config-file", str(config), "--no-incremental", "--no-site-packages", "--follow-imports=skip", "--ignore-missing-imports", "--check-untyped-defs", "."], snapshot, timeout))
        else:
            checks.append({"name": "python", "status": "not_applicable", "output": "No Python sources; no supported static profile executed"})
        if dependencies:
            checks.append(run_dependency_audit(root, timeout=timeout))
        else:
            checks.append({"name": "dependency_audit", "status": "not_applicable",
                           "output": "No Python dependency manifest detected"})
    status = "passed" if files and all(c["status"] in {"passed", "not_applicable"} for c in checks) else "failed" if any(c["status"] == "failed" for c in checks) else "unverified"
    return {"status": status, "profile": "python-offline", "source_files": len(files), "checks": checks}


def run_dependency_audit(root: Path, *, timeout: float = 120) -> dict:
    """Audit dependency manifests with pip-audit (queries PyPI; needs network).

    Status mapping is honest: a vulnerability finding is "failed", an
    unreachable registry or missing tool is "unavailable" (never a pass).
    """
    if importlib.util.find_spec("pip_audit") is None:
        return {"name": "dependency_audit", "status": "unavailable",
                "output": "pip-audit is not installed in the host environment"}
    manifests = sorted(
        path for name in ("requirements.txt",)
        if (root / name).is_file()
        for path in [root / name]
    )
    if not manifests:
        return {"name": "dependency_audit", "status": "not_applicable",
                "output": "No requirements.txt to audit"}
    command = [sys.executable, "-I", "-m", "pip_audit", "-l", "-r", str(manifests[0]), "--format", "json", "--progress-spinner", "off"]
    try:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(command, cwd=str(root), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            output.seek(0)
            text = output.read(16384).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"name": "dependency_audit", "status": "timeout", "exit_code": None,
                "output": "Dependency audit exceeded its time limit"}
    except OSError:
        return {"name": "dependency_audit", "status": "unavailable",
                "output": "Unable to start pip-audit"}
    if completed.returncode != 0:
        # pip-audit exits nonzero both on findings and on tool failure; the
        # JSON output distinguishes them. Parse it, otherwise stay honest.
        try:
            payload = json.loads(text[text.index("{"):])
            vulns = [v for dep in payload.get("dependencies", []) for v in dep.get("vulns", [])]
        except (ValueError, json.JSONDecodeError):
            return {"name": "dependency_audit", "status": "unavailable", "exit_code": completed.returncode,
                    "output": text.strip()[:500] or "pip-audit could not reach the vulnerability service"}
        ids = sorted({v.get("id", "?") for v in vulns})
        return {"name": "dependency_audit", "status": "failed", "exit_code": completed.returncode,
                "output": f"{len(vulns)} vulnerabilities: {', '.join(ids)}"}
    return {"name": "dependency_audit", "status": "passed", "exit_code": 0, "output": "No known vulnerabilities"}


def write_static_report(root: Path, result: dict) -> Path:
    folder = root / "docs"
    if folder.is_symlink() or (folder.exists() and folder.is_junction()):
        raise ValueError("Report directory must not be a link")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "static_gate.json"
    if path.is_symlink():
        raise ValueError("Report file must not be a link")
    fd, temporary = tempfile.mkstemp(prefix=".static-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
