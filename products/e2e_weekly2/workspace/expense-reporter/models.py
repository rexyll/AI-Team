"""Expense report data models."""

from dataclasses import dataclass
from decimal import Decimal
from datetime import date


@dataclass(frozen=True)
class ExpenseRecord:
    """A single expense record from CSV."""
    date: date
    employee: str
    category: str
    amount: Decimal
    currency: str
    note: str
