import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class CsvRecord:
    date: str
    employee: str
    category: str
    amount: str
    currency: str
    note: str


@dataclass(frozen=True)
class ParseError:
    row_num: int
    reason: str


REQUIRED_COLUMNS = ("date", "employee", "category", "amount", "currency", "note")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AMOUNT_RE = re.compile(r"^\d+\.\d{2}$")


def _validate_date(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        parts = value.split("-")
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if not (1 <= m <= 12 and 1 <= d <= 31):
            return False
    except ValueError:
        return False
    return True


def _validate_amount(value: str) -> bool:
    return bool(AMOUNT_RE.match(value))


def parse_csv(source: str | Path) -> Tuple[List[CsvRecord], List[ParseError]]:
    path = Path(source)
    raw = path.read_bytes()

    if raw[:3] == b"\xef\xbb\xbf":
        text = raw[3:].decode("utf-8")
    else:
        text = raw.decode("utf-8")

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], []

    header = [h.strip() for h in header]
    errors: List[ParseError] = []
    records: List[CsvRecord] = []

    if header[: len(REQUIRED_COLUMNS)] != list(REQUIRED_COLUMNS):
        errors.append(ParseError(row_num=1, reason="missing required columns"))
        return records, errors

    for row_num, row in enumerate(reader, start=2):
        if len(row) < len(REQUIRED_COLUMNS):
            errors.append(
                ParseError(
                    row_num=row_num,
                    reason=f"field count mismatch: expected {len(REQUIRED_COLUMNS)}, got {len(row)}",
                )
            )
            continue

        date_val = row[0].strip()
        employee_val = row[1].strip()
        category_val = row[2].strip()
        amount_val = row[3].strip()
        currency_val = row[4].strip()
        note_val = row[5].strip()

        row_errors: List[str] = []
        if not _validate_date(date_val):
            row_errors.append(f"invalid date format: {date_val!r}")
        if not _validate_amount(amount_val):
            row_errors.append(f"invalid amount format: {amount_val!r}")
        if currency_val != "CNY":
            row_errors.append(f"unsupported currency: {currency_val!r}")

        if row_errors:
            errors.append(ParseError(row_num=row_num, reason="; ".join(row_errors)))
            continue

        records.append(
            CsvRecord(
                date=date_val,
                employee=employee_val,
                category=category_val,
                amount=amount_val,
                currency=currency_val,
                note=note_val,
            )
        )

    return records, errors
