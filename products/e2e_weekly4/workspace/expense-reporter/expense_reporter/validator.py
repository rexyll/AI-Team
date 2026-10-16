"""Single-record validation for expense reports (REQ-002)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable


@dataclass(frozen=True, order=False)
class ValidationError:
    """Describes a single validation violation on one record."""

    line_number: int
    rule: str
    field: str
    value: object

    def __str__(self) -> str:
        return (
            f"Line {self.line_number}: '{self.rule}' failed — "
            f"field='{self.field}', value={self.value!r}"
        )

    def __repr__(self) -> str:
        return (
            f"ValidationError(line_number={self.line_number}, "
            f"rule={self.rule!r}, field={self.field!r}, value={self.value!r})"
        )


_VALID_CATEGORIES = frozenset({"travel", "meal", "office", "other"})
_DEFAULT_MAX_AGE_DAYS = 365


def _as_date(value: object) -> date | None:
    """Attempt to coerce *value* into a :class:`datetime.date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def validate(
    records: Iterable[dict[str, object]],
    *,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    today: date | None = None,
) -> list[ValidationError]:
    """Validate expense records and return a list of violations.

    Parameters
    ----------
    records:
        Each item is a dict representing one parsed row.  Required keys are
        ``amount``, ``date``, ``category``, ``note``, and ``currency``.  An
        optional ``line_number`` key (1-based) is used when reporting errors.
    max_age_days:
        Maximum allowed age of a record in days before today.  Defaults to
        365.
    today:
        Mockable reference date.  Defaults to the current calendar date.

    Returns
    -------
    list[ValidationError]
        Every individual rule violation is emitted separately so that a
        single record can produce multiple errors.
    """
    if today is None:
        today = date.today()
    cutoff = today - timedelta(days=max_age_days)

    errors: list[ValidationError] = []

    for idx, record in enumerate(records, start=1):
        line_no = record.get("line_number", idx)

        # --- rule 1: amount > 0 ---
        amount = record.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            errors.append(ValidationError(line_no, "amount > 0", "amount", amount))

        # --- rule 2: date within window ---
        rec_date = _as_date(record.get("date"))
        if rec_date is None:
            errors.append(
                ValidationError(line_no, "valid date", "date", record.get("date"))
            )
        elif rec_date > today:
            errors.append(
                ValidationError(line_no, "date <= today", "date", record.get("date"))
            )
        elif rec_date < cutoff:
            errors.append(
                ValidationError(line_no, "date >= cutoff", "date", record.get("date"))
            )

        # --- rule 3: category in allowed set ---
        category = record.get("category")
        if category not in _VALID_CATEGORIES:
            errors.append(ValidationError(line_no, "valid category", "category", category))

        # --- rule 4: note non-empty after stripping ---
        note = record.get("note")
        if not isinstance(note, str) or not note.strip():
            errors.append(ValidationError(line_no, "non-empty note", "note", note))

        # --- rule 5: currency == CNY ---
        currency = record.get("currency")
        if currency != "CNY":
            errors.append(ValidationError(line_no, "currency == CNY", "currency", currency))

    return errors
