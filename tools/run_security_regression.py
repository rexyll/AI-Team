from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests"


def _security_tests() -> list[str]:
    """Return the repository's security regression modules deterministically."""
    patterns = (
        "test_*security*.py",
        "test_*dependency*.py",
        "test_*egress*.py",
        "test_*secret*.py",
        "test_*prompt_injection*.py",
        "test_*evidence*.py",
    )
    paths = {
        path
        for pattern in patterns
        for path in TEST_ROOT.glob(pattern)
        if path.is_file()
    }
    return [str(path.relative_to(ROOT)) for path in sorted(paths)]


def main() -> int:
    tests = _security_tests()
    if not tests:
        print("No security regression tests were found.", file=sys.stderr)
        return 2

    print("Security regression suite:")
    for path in tests:
        print(f"  {path}")

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
