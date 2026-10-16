"""Tests for expense_reporter.parser."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure the package can be imported regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from expense_reporter.parser import ParseResult, ExpenseRow, parse_csv  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_csv(tmp: Path, content: str, suffix: str = ".csv") -> Path:
    p = tmp / f"test{suffix}"
    p.write_text(content, encoding="utf-8")
    return p


def _write_csv_bytes(tmp: Path, data: bytes, suffix: str = ".csv") -> Path:
    p = tmp / f"test{suffix}"
    p.write_bytes(data)
    return p


# ── fixture: minimal valid CSV ───────────────────────────────────────────────

VALID_CSV = (
    "date,employee,category,amount,currency,note\n"
    "2024-01-15,Alice Smith,Travel,120.50,USD,Flight to NY\n"
    "2024-01-16,Bob Jones,Meals,45.00,EUR,Lunch with client\n"
)

EXPECTED_ROWS = [
    ExpenseRow(
        date="2024-01-15",
        employee="Alice Smith",
        category="Travel",
        amount="120.50",
        currency="USD",
        note="Flight to NY",
    ),
    ExpenseRow(
        date="2024-01-16",
        employee="Bob Jones",
        category="Meals",
        amount="45.00",
        currency="EUR",
        note="Lunch with client",
    ),
]


# ── tests ────────────────────────────────────────────────────────────────────

def test_parse_valid_csv(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, VALID_CSV)
    result = parse_csv(p)
    assert result.rows == EXPECTED_ROWS
    assert result.errors == []


def test_parse_utf8_bom(tmp_path: Path) -> None:
    bom = b"\xef\xbb\xbf"
    p = _write_csv_bytes(tmp_path, bom + VALID_CSV.encode("utf-8"))
    result = parse_csv(p)
    assert result.rows == EXPECTED_ROWS
    assert result.errors == []


def test_parse_missing_required_column(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "date,employee,note\n2024-01-01,Alice,hello\n")
    result = parse_csv(p)
    assert result.rows == []
    assert len(result.errors) == 1
    assert "currency" in result.errors[0].lower() or "amount" in result.errors[0].lower()


def test_parse_bad_row_short_columns(tmp_path: Path) -> None:
    content = (
        "date,employee,category,amount,currency,note\n"
        "2024-01-01,Alice,Travel\n"  # missing amount, currency, note
    )
    p = _write_csv(tmp_path, content)
    result = parse_csv(p)
    assert result.rows == []
    assert len(result.errors) == 1
    assert "Row 2" in result.errors[0]


def test_parse_mixed_good_and_bad_rows(tmp_path: Path) -> None:
    content = (
        "date,employee,category,amount,currency,note\n"
        "2024-01-01,Alice,Travel,100,USD,good\n"
        "2024-01-02,Bob\n"  # bad row
        "2024-01-03,Carol,Food,20,EUR,also good\n"
    )
    p = _write_csv(tmp_path, content)
    result = parse_csv(p)
    assert len(result.rows) == 2
    assert len(result.errors) == 1
    assert "Row 3" in result.errors[0]


def test_parse_empty_file(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "")
    result = parse_csv(p)
    assert result.rows == []
    assert result.errors == []


def test_parse_headers_only(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "date,employee,category,amount,currency,note\n")
    result = parse_csv(p)
    assert result.rows == []
    assert result.errors == []


def test_result_dataclass_types() -> None:
    result = ParseResult(rows=[], errors=[])
    assert isinstance(result.rows, list)
    assert isinstance(result.errors, list)


def test_expense_row_frozen() -> None:
    row = ExpenseRow(
        date="2024-01-01",
        employee="Alice",
        category="Travel",
        amount="100",
        currency="USD",
        note="test",
    )
    try:
        row.date = "changed"
        assert False, "Should not be mutable"
    except AttributeError:
        pass  # expected


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
