"""CSV parser for expense reports.

Reads UTF-8 CSV files (with optional BOM), validates required columns,
and returns parsed rows together with a list of parse errors for bad lines.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator


REQUIRED_COLUMNS = ("date", "employee", "category", "amount", "currency", "note")


@dataclass(frozen=True)
class ExpenseRow:
    """One validated expense row."""

    date: str
    employee: str
    category: str
    amount: str
    currency: str
    note: str


@dataclass
class ParseResult:
    """Result of parsing an expense CSV."""

    rows: list[ExpenseRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _read_bytes(path: os.PathLike | str) -> bytes:
    """Read file as raw bytes so we can strip BOM ourselves."""
    with open(path, "rb") as f:
        return f.read()


def _strip_bom(data: bytes) -> bytes:
    """Strip UTF-8 BOM if present."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:]
    return data


def _column_indices(headers: list[str]) -> dict[str, int] | None:
    """Return {required_name: index} for all required columns, or None if missing."""
    headers_lower = [h.strip().lower() for h in headers]
    indices: dict[str, int] = {}
    for req in REQUIRED_COLUMNS:
        try:
            indices[req] = headers_lower.index(req)
        except ValueError:
            return None
    return indices


def _parse_row(
    values: list[str], col_idx: dict[str, int], row_num: int
) -> ExpenseRow | str:
    """Validate and build an ExpenseRow, or return an error string."""
    max_idx = max(col_idx.values())
    if len(values) <= max_idx:
        return f"Row {row_num}: insufficient columns (expected at least {max_idx + 1}, got {len(values)})"
    try:
        return ExpenseRow(
            date=values[col_idx["date"]].strip(),
            employee=values[col_idx["employee"]].strip(),
            category=values[col_idx["category"]].strip(),
            amount=values[col_idx["amount"]].strip(),
            currency=values[col_idx["currency"]].strip(),
            note=values[col_idx["note"]].strip(),
        )
    except Exception as exc:
        return f"Row {row_num}: {exc}"


def parse_csv(path: os.PathLike | str) -> ParseResult:
    """Parse an expense CSV file.

    Args:
        path: Path to a UTF-8 (optionally BOM-marked) CSV file.

    Returns:
        ParseResult containing successful rows and error messages for bad lines.
    """
    result = ParseResult()
    raw = _read_bytes(path)
    text = _strip_bom(raw).decode("utf-8")
    reader = csv.reader(io.StringIO(text))

    headers: list[str] | None = None
    col_idx: dict[str, int] | None = None

    for row_num, row in enumerate(reader, start=1):
        # Skip entirely blank lines
        if not row or all(cell.strip() == "" for cell in row):
            continue

        if headers is None:
            headers = row
            col_idx = _column_indices(row)
            if col_idx is None:
                missing = [c for c in REQUIRED_COLUMNS if c not in [h.strip().lower() for h in row]]
                result.errors.append(f"Header row missing required column(s): {', '.join(missing)}")
                return result
            continue

        if col_idx is None:
            # Should not happen, but safeguard
            result.errors.append(f"Row {row_num}: no valid header found")
            continue

        expense = _parse_row(row, col_idx, row_num)
        if isinstance(expense, str):
            result.errors.append(expense)
        else:
            result.rows.append(expense)

    return result
