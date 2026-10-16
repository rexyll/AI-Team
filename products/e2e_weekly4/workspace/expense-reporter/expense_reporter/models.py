"""Expense report record model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ExpenseRecord:
    """Represents a single expense report record."""

    amount: float
    date: date
    category: str
    note: str
    currency: str
    line_number: int = 0
    raw: dict[str, Any] = field(default_factory=dict)
