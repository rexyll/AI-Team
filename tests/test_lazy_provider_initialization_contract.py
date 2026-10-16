"""Regression guards for lazy provider initialization.

Phase 8.8 removed the import-time side effects from ``config/model.py``
(eager key validation + eager OpenAI client construction). These tests
prove that the full agent import chain succeeds without ``AGNES_API_KEY``
and that the client is only resolved - and only fails - on first actual
use. Each check runs in a clean subprocess so in-memory state from other
tests cannot mask an import-time regression.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_without_key(code: str) -> subprocess.CompletedProcess:
    """Run ``code`` in a fresh interpreter with every AGNES key variant stripped.

    The rotation feature accepts numbered keys (``AGNES_API_KEY1``...), so a
    subprocess that keeps them would legitimately still be configured.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AGNES_API_KEY")
    }
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_agent_import_chain_succeeds_without_api_key() -> None:
    result = _run_without_key("import main")

    assert result.returncode == 0, result.stderr


def test_provider_module_imports_without_api_key() -> None:
    result = _run_without_key("import runtime.llm.provider")

    assert result.returncode == 0, result.stderr


def test_provider_llm_constructs_without_api_key() -> None:
    result = _run_without_key(
        "from runtime.llm.provider import ProviderLLM\n"
        "llm = ProviderLLM(model='stub-model')\n"
        "assert llm.model == 'stub-model'\n"
    )

    assert result.returncode == 0, result.stderr


def test_get_client_fails_only_on_use_without_key() -> None:
    # ``load_dotenv()`` may legitimately restore the key from a developer's
    # ``.env`` during import, so the key is removed *after* import and
    # before first use - exactly the boundary this contract guards.
    code = (
        "import os\n"
        "def _pop_keys():\n"
        "    for name in [v for v in os.environ if v.startswith('AGNES_API_KEY')]:\n"
        "        os.environ.pop(name, None)\n"
        "_pop_keys()\n"
        "import config.model as m\n"
        "_pop_keys()\n"
        "try:\n"
        "    m.get_client()\n"
        "except RuntimeError as exc:\n"
        "    assert 'AGNES_API_KEY' in str(exc)\n"
        "else:\n"
        "    raise SystemExit('get_client must fail without AGNES_API_KEY')\n"
    )
    result = _run_without_key(code)

    assert result.returncode == 0, result.stderr


def test_get_client_is_cached_after_first_construction() -> None:
    result = _run_without_key(
        "import os\n"
        "os.environ['AGNES_API_KEY'] = 'subprocess-stub-key'\n"
        "import config.model as m\n"
        "first = m.get_client()\n"
        "second = m.get_client()\n"
        "assert first is second\n"
    )

    assert result.returncode == 0, result.stderr
