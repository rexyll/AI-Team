"""CSV parsing for expense reports (REQ-001)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import IO

from .models import ExpenseRecord


@dataclass
class ParseError:
    """Describes a single parsing error on one CSV row."""

    line_number: int
    reason: str


_REQUIRED_COLUMNS = ("date", "employee", "category", "amount", "currency", "note")


def _parse_date(value: str) -> date | None:
    """Return a date if *value* matches YYYY-MM-DD, else None."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _parse_amount(value: str) -> float | None:
    """Return a float if *value* is a valid decimal string, else None."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"-?\d+\.\d{2}", value):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_csv(
    source: str | bytes | Path | IO[str] | IO[bytes],
) -> tuple[list[ExpenseRecord], list[ParseError]]:
    """Parse a CSV expense file and return (records, errors).

    Parameters
    ----------
    source :
        File path (str, bytes, or :class:`Path`) or an open text/binary file-like
        object.  When a path is given the file is opened with UTF-8-sig encoding
        (handles optional BOM).

    Returns
    -------
    tuple[list[ExpenseRecord], list[ParseError]]
        Valid records and a list of per-row parse errors.
    """
    records: list[ExpenseRecord] = []
    errors: list[ParseError] = []

    should_close = False
    try:
        if isinstance(source, (str, bytes, Path)):
            with open(source, encoding="utf-8-sig", newline="") as fh:
                should_close = True
                reader = csv.DictReader(fh)
                header = reader.fieldnames
                if header is None:
                    errors.append(ParseError(line_number=1, reason="empty file"))
                    return records, errors
                _check_header(header, errors)
                for row_idx, row in enumerate(reader, start=2):
                    _process_row(row, row_idx, reader.fieldnames, records, errors)
        else:
            # Assume already-open file-like object; caller is responsible for closing.
            text = hasattr(source, "encoding")
            if text:
                reader = csv.DictReader(source)
            else:
                wrapper = io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(wrapper)
            header = reader.fieldnames
            if header is None:
                errors.append(ParseError(line_number=1, reason="empty file"))
                return records, errors
            _check_header(header, errors)
            for row_idx, row in enumerate(reader, start=2):
                _process_row(row, row_idx, reader.fieldnames, records, errors)
    finally:
        if should_close and hasattr(source, "close"):
            source.close()

    return records, errors


def _check_header(
    header: list[str], errors: list[ParseError]
) -> None:
    """Validate that the header contains all required columns."""
    if len(header) < len(_REQUIRED_COLUMNS):
        missing = [c for c in _REQUIRED_COLUMNS if c not in header]
        errors.append(
            ParseError(
                line_number=1,
                reason=f"missing required columns: {', '.join(missing)}",
            )
        )
        return
    for col in _REQUIRED_COLUMNS:
        try:
            header.index(col)
        except ValueError:
            errors.append(
                ParseError(line_number=1, reason=f"missing required column: {col}")
            )
            return


def _process_row(
    row: dict[str, str | None],
    line_number: int,
    header: list[str] | None,
    records: list[ExpenseRecord],
    errors: list[ParseError],
) -> None:
    """Parse and validate a single CSV row."""
    # Check that no required field is missing/None (catches short rows padded by
    # DictReader).
    for col in _REQUIRED_COLUMNS:
        val = row.get(col)
        if val is None or val == "":
            errors.append(
                ParseError(
                    line_number=line_number,
                    reason=f"missing required field: {col}",
                )
            )
            return

    date_str = row.get("date")
    amount_str = row.get("amount")
    currency = row.get("currency")

    # --- date ---
    parsed_date = _parse_date(date_str)
    if parsed_date is None:
        errors.append(
            ParseError(
                line_number=line_number,
                reason=f"invalid date format: {date_str!r}",
            )
        )
        return

    # --- amount ---
    parsed_amount = _parse_amount(amount_str)
    if parsed_amount is None:
        errors.append(
            ParseError(
                line_number=line_number,
                reason=f"invalid amount format: {amount_str!r}",
            )
        )
        return

    # --- currency ---
    if currency != "CNY":
        errors.append(
            ParseError(
                line_number=line_number,
                reason=f"currency must be CNY, got {currency!r}",
            )
        )
        return

    record = ExpenseRecord(
        date=parsed_date,
        category=row.get("category", ""),
        amount=parsed_amount,
        currency="CNY",
        note=row.get("note", ""),
        line_number=line_number,
        raw=dict(row),
    )
    records.append(record)
