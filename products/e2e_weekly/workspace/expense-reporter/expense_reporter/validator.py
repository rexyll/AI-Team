"""Expense row validator.

Validates a single ExpenseRow against business rules:
  - amount > 0
  - date within allowed time window (default 365 days from today)
  - category in {travel, meal, office, other}
  - note is not empty
  - currency == CNY

When multiple rules are violated, all errors are collected and returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from .parser import ExpenseRow

ALLOWED_CATEGORIES = frozenset({"travel", "meal", "office", "other"})
DEFAULT_DATE_WINDOW_DAYS = 365


@dataclass(frozen=True)
class ValidationError:
    """A single validation error."""

    field: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a single ExpenseRow."""

    row: ExpenseRow
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _validate_amount(row: ExpenseRow) -> list[ValidationError]:
    errors: list[ValidationError] = []
    try:
        amount = float(row.amount)
    except (ValueError, TypeError):
        errors.append(ValidationError("amount", f"Invalid amount value: {row.amount!r}"))
    else:
        if amount <= 0:
            errors.append(ValidationError("amount", f"Amount must be > 0, got {amount}"))
    return errors


def _validate_date(row: ExpenseRow, *, window_days: int = DEFAULT_DATE_WINDOW_DAYS) -> list[ValidationError]:
    errors: list[ValidationError] = []
    try:
        expense_date = datetime.strptime(row.date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append(ValidationError("date", f"Invalid date format: {row.date!r}, expected YYYY-MM-DD"))
        return errors

    today = date.today()
    if expense_date > today:
        errors.append(ValidationError("date", f"Date {row.date} is in the future"))
        return errors

    cutoff = today - timedelta(days=window_days)
    if expense_date < cutoff:
        errors.append(ValidationError("date", f"Date {row.date} is outside the allowed window of {window_days} days"))
    return errors


def _validate_category(row: ExpenseRow) -> list[ValidationError]:
    category = row.category.lower().strip()
    if category not in ALLOWED_CATEGORIES:
        return [ValidationError("category", f"Invalid category {row.category!r}, must be one of {sorted(ALLOWED_CATEGORIES)}")]
    return []


def _validate_note(row: ExpenseRow) -> list[ValidationError]:
    if not row.note:
        return [ValidationError("note", "Note must not be empty")]
    return []


def _validate_currency(row: ExpenseRow) -> list[ValidationError]:
    currency = row.currency.strip().upper()
    if currency != "CNY":
        return [ValidationError("currency", f"Currency must be CNY, got {row.currency!r}")]
    return []


def validate_row(row: ExpenseRow, *, window_days: int = DEFAULT_DATE_WINDOW_DAYS) -> ValidationResult:
    """Validate a single ExpenseRow.

    Args:
        row: The expense row to validate.
        window_days: Number of days back from today that the date must fall within.
                     Defaults to 365.

    Returns:
        ValidationResult containing the row and any errors found.
    """
    errors: list[ValidationError] = []
    errors.extend(_validate_amount(row))
    errors.extend(_validate_date(row, window_days=window_days))
    errors.extend(_validate_category(row))
    errors.extend(_validate_note(row))
    errors.extend(_validate_currency(row))
    return ValidationResult(row=row, errors=errors)


def validate_rows(rows: Iterable[ExpenseRow], *, window_days: int = DEFAULT_DATE_WINDOW_DAYS) -> list[ValidationResult]:
    """Validate multiple ExpenseRows.

    Args:
        rows: Iterable of ExpenseRow instances.
        window_days: Number of days back from today that dates must fall within.

    Returns:
        List of ValidationResult, one per input row.
    """
    return [validate_row(row, window_days=window_days) for row in rows]
