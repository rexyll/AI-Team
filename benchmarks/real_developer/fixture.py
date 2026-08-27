from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

import security.workspace as workspace_module
from security.workspace import set_default_workspace_root


_FIXTURE_FILES: dict[str, str] = {
    "app/__init__.py": "",
    "app/utils/__init__.py": "",
    "app/utils/helpers.py": '''"""Shared utility module used by the serial benchmark workload."""

from __future__ import annotations

import re
from typing import Iterable, TypeVar


T = TypeVar("T")


def normalize_name(value: str) -> str:
    """Trim a name and collapse repeated whitespace."""
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return re.sub(r"\\s+", " ", value).strip()


def paginate(items: Iterable[T], page: int = 1, page_size: int = 20) -> dict[str, object]:
    """Return a one-based page view over an iterable."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    values = list(items)
    total = len(values)
    pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return {
        "items": values[start : start + page_size],
        "total": total,
        "page": page,
        "pages": pages,
    }


def is_non_empty(value: str) -> bool:
    """Return whether a normalized string contains useful content."""
    return bool(normalize_name(value))
''',
    "app/utils/date_helpers.py": '''"""Date helpers for the parallel benchmark workload."""

from __future__ import annotations

from datetime import date, datetime


def format_date(value: datetime | date) -> str:
    """Return a stable ISO date/datetime representation."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.strftime("%Y-%m-%d")
''',
    "app/utils/name_helpers.py": '''"""Name helpers for the parallel benchmark workload."""

from __future__ import annotations

import re


def normalize_name(value: str) -> str:
    """Trim a name and collapse repeated whitespace."""
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return re.sub(r"\\s+", " ", value).strip()
''',
    "app/utils/pagination.py": '''"""Pagination helpers for the parallel benchmark workload."""

from __future__ import annotations

from typing import Iterable, TypeVar

T = TypeVar("T")


def paginate(items: Iterable[T], page: int = 1, page_size: int = 20) -> dict[str, object]:
    """Return a one-based page view over an iterable."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    values = list(items)
    total = len(values)
    pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return {"items": values[start : start + page_size], "total": total, "page": page, "pages": pages}
''',
    "tests/__init__.py": "",
    "tests/test_helpers.py": '''from app.utils.helpers import is_non_empty, normalize_name, paginate


def test_normalize_name_collapses_whitespace() -> None:
    assert normalize_name("  Ada   Lovelace ") == "Ada Lovelace"


def test_paginate_returns_page_metadata() -> None:
    assert paginate([1, 2, 3], page=2, page_size=2) == {
        "items": [3],
        "total": 3,
        "page": 2,
        "pages": 2,
    }


def test_is_non_empty_uses_normalized_value() -> None:
    assert is_non_empty("  value ") is True
    assert is_non_empty("   ") is False
''',
    "tests/test_date_helpers.py": '''from datetime import date, datetime

from app.utils.date_helpers import format_date


def test_format_date_supports_date_and_datetime() -> None:
    assert format_date(date(2024, 3, 15)) == "2024-03-15"
    assert format_date(datetime(2024, 3, 15, 10, 30)) == "2024-03-15 10:30:00"
''',
    "tests/test_name_helpers.py": '''import pytest

from app.utils.name_helpers import normalize_name


def test_normalize_name_collapses_whitespace() -> None:
    assert normalize_name("  Ada   Lovelace ") == "Ada Lovelace"


def test_normalize_name_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        normalize_name(123)
''',
    "tests/test_pagination.py": '''import pytest

from app.utils.pagination import paginate


def test_paginate_returns_page_metadata() -> None:
    assert paginate([1, 2, 3], page=2, page_size=2) == {
        "items": [3],
        "total": 3,
        "page": 2,
        "pages": 2,
    }


def test_paginate_rejects_invalid_page() -> None:
    with pytest.raises(ValueError):
        paginate([1], page=0)
''',
}


@contextmanager
def isolated_benchmark_workspace() -> Iterator[Path]:
    """Create a fresh benchmark project and temporarily make it the sandbox root."""
    previous = workspace_module.DEFAULT_SANDBOX
    with TemporaryDirectory(prefix="ai_team_real_developer_") as directory:
        root = Path(directory).resolve()
        for relative, content in _FIXTURE_FILES.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        set_default_workspace_root(root)
        try:
            yield root
        finally:
            workspace_module.DEFAULT_SANDBOX = previous


def fixture_files() -> dict[str, str]:
    """Return a copy of the fixture manifest for contract tests."""
    return dict(_FIXTURE_FILES)
