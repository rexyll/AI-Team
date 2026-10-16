"""Tests for expense_reporter.validator."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

# Ensure the package root is on sys.path so imports work from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expense_reporter.parser import ExpenseRow
from expense_reporter.validator import (
    ALLOWED_CATEGORIES,
    DEFAULT_DATE_WINDOW_DAYS,
    ValidationResult,
    validate_row,
    validate_rows,
)


class TestValidateRow(unittest.TestCase):
    """Tests for validate_row with a valid row."""

    def _valid_row(self, **overrides):
        defaults = dict(
            date=date.today().strftime("%Y-%m-%d"),
            employee="test",
            category="travel",
            amount="100.00",
            currency="CNY",
            note="something",
        )
        defaults.update(overrides)
        return ExpenseRow(**defaults)

    # --- amount ---

    def test_valid_amount(self):
        result = validate_row(self._valid_row(amount="50.00"))
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_zero_amount(self):
        result = validate_row(self._valid_row(amount="0"))
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].field, "amount")

    def test_negative_amount(self):
        result = validate_row(self._valid_row(amount="-10"))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "amount")

    def test_invalid_amount_string(self):
        result = validate_row(self._valid_row(amount="abc"))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "amount")

    # --- date ---

    def test_today_date_valid(self):
        result = validate_row(self._valid_row(date=date.today().strftime("%Y-%m-%d")))
        self.assertTrue(result.is_valid)

    def test_future_date_invalid(self):
        future = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        result = validate_row(self._valid_row(date=future))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "date")

    def test_date_too_old(self):
        old = (date.today() - timedelta(days=DEFAULT_DATE_WINDOW_DAYS + 1)).strftime("%Y-%m-%d")
        result = validate_row(self._valid_row(date=old))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "date")

    def test_date_at_cutoff_valid(self):
        cutoff = (date.today() - timedelta(days=DEFAULT_DATE_WINDOW_DAYS)).strftime("%Y-%m-%d")
        result = validate_row(self._valid_row(date=cutoff))
        self.assertTrue(result.is_valid)

    def test_invalid_date_format(self):
        result = validate_row(self._valid_row(date="not-a-date"))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "date")

    def test_custom_window_days(self):
        result = validate_row(
            self._valid_row(date=(date.today() - timedelta(days=10)).strftime("%Y-%m-%d")),
            window_days=5,
        )
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "date")

    # --- category ---

    def test_valid_category(self):
        for cat in ALLOWED_CATEGORIES:
            with self.subTest(category=cat):
                result = validate_row(self._valid_row(category=cat))
                self.assertTrue(result.is_valid)

    def test_invalid_category(self):
        result = validate_row(self._valid_row(category="entertainment"))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "category")

    # --- note ---

    def test_non_empty_note_valid(self):
        result = validate_row(self._valid_row(note="coffee"))
        self.assertTrue(result.is_valid)

    def test_empty_note_invalid(self):
        result = validate_row(self._valid_row(note=""))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "note")

    # --- currency ---

    def test_cny_valid(self):
        result = validate_row(self._valid_row(currency="CNY"))
        self.assertTrue(result.is_valid)

    def test_usd_invalid(self):
        result = validate_row(self._valid_row(currency="USD"))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field, "currency")

    # --- multiple errors ---

    def test_multiple_errors(self):
        result = validate_row(
            self._valid_row(
                amount="-5",
                date=(date.today() + timedelta(days=1)).strftime("%Y-%m-%d"),
                category="entertainment",
                note="",
                currency="USD",
            )
        )
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 5)
        error_fields = [e.field for e in result.errors]
        self.assertIn("amount", error_fields)
        self.assertIn("date", error_fields)
        self.assertIn("category", error_fields)
        self.assertIn("note", error_fields)
        self.assertIn("currency", error_fields)


class TestValidateRows(unittest.TestCase):
    """Tests for validate_rows helper."""

    def test_valid_and_invalid(self):
        rows = [
            ExpenseRow(
                date=date.today().strftime("%Y-%m-%d"),
                employee="a",
                category="travel",
                amount="10",
                currency="CNY",
                note="ok",
            ),
            ExpenseRow(
                date="2020-01-01",
                employee="b",
                category="invalid",
                amount="-1",
                currency="USD",
                note="",
            ),
        ]
        results = validate_rows(rows)
        self.assertTrue(results[0].is_valid)
        self.assertFalse(results[1].is_valid)
        self.assertGreater(len(results[1].errors), 1)


if __name__ == "__main__":
    unittest.main()
