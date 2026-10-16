"""CSV parser for expense reports.

Reads UTF-8 encoded (BOM-tolerant) CSV files and parses expense records.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Tuple

from .models import ExpenseRecord


@dataclass
class ParseError:
    """Error encountered while parsing a CSV row."""
    row_number: int
    reason: str


REQUIRED_COLUMNS = ["date", "employee", "category", "amount", "currency", "note"]


def _parse_date(value: str) -> date:
    """Parse a date string in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid date format: {value!r}")


def _parse_amount(value: str) -> Decimal:
    """Parse an amount string to Decimal."""
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {value!r}")


def parse_csv(content: str) -> Tuple[List[ExpenseRecord], List[ParseError]]:
    """Parse CSV content into ExpenseRecord objects.

    Args:
        content: UTF-8 encoded CSV string (may have BOM).

    Returns:
        A tuple of (records, errors) where:
        - records: list of successfully parsed ExpenseRecord objects
        - errors: list of ParseError for failed rows
    """
    # Strip BOM if present
    if content.startswith("\ufeff"):
        content = content[1:]

    reader = csv.DictReader(io.StringIO(content))

    # Validate header columns
    if reader.fieldnames is None:
        return [], [ParseError(row_number=1, reason="Empty CSV file")]

    # Normalize header names (strip whitespace, lowercase for comparison)
    headers = [h.strip().lower() if h else "" for h in reader.fieldnames]

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in headers]
    if missing_columns:
        return [], [ParseError(row_number=1, reason=f"Missing required columns: {', '.join(missing_columns)}")]

    # Build mapping from normalized name to original header
    header_map = {}
    for normalized, original in zip(headers, reader.fieldnames):
        if normalized not in header_map:
            header_map[normalized] = original

    records: List[ExpenseRecord] = []
    errors: List[ParseError] = []

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        # Check field count
        if len(row) != 6:
            errors.append(ParseError(
                row_number=row_num,
                reason=f"Expected 6 fields, got {len(row)}"
            ))
            continue

        try:
            record = ExpenseRecord(
                date=_parse_date(row[header_map["date"]].strip()),
                employee=row[header_map["employee"]].strip(),
                category=row[header_map["category"]].strip(),
                amount=_parse_amount(row[header_map["amount"]].strip()),
                currency=row[header_map["currency"]].strip(),
                note=row[header_map["note"]].strip(),
            )
            records.append(record)
        except ValueError as e:
            errors.append(ParseError(
                row_number=row_num,
                reason=str(e)
            ))

    return records, errors


def parse_csv_file(filepath: str) -> Tuple[List[ExpenseRecord], List[ParseError]]:
    """Parse a CSV file into ExpenseRecord objects.

    Args:
        filepath: Path to the CSV file (UTF-8 encoded, BOM-tolerant).

    Returns:
        A tuple of (records, errors).
    """
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()
    return parse_csv(content)
