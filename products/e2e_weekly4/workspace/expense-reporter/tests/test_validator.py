"""Tests for expense_reporter.validator (REQ-002)."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta

# Ensure the repo root is on sys.path regardless of cwd.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from expense_reporter.validator import ValidationError, validate  # noqa: E402


class TestValidate(unittest.TestCase):
    """Cover every validation rule with passing and failing cases."""

    def _ok_record(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "amount": 10.0,
            "date": date.today(),
            "category": "travel",
            "note": "lunch",
            "currency": "CNY",
        }
        base.update(overrides)
        return base

    # ------------------------------------------------------------------
    # Rule 1: amount > 0
    # ------------------------------------------------------------------
    def test_amount_zero(self) -> None:
        errors = validate([self._ok_record(amount=0)])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "amount > 0")
        self.assertEqual(errors[0].value, 0)

    def test_amount_negative(self) -> None:
        errors = validate([self._ok_record(amount=-5)])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "amount > 0")

    def test_amount_string_fails(self) -> None:
        errors = validate([self._ok_record(amount="ten")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "amount > 0")

    def test_amount_positive_succeeds(self) -> None:
        errors = validate([self._ok_record(amount=1)])
        self.assertEqual(errors, [])

    # ------------------------------------------------------------------
    # Rule 2: date not later than today, not earlier than cutoff
    # ------------------------------------------------------------------
    def test_date_in_future(self) -> None:
        errors = validate([self._ok_record(date=date.today() + timedelta(days=1))])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "date <= today")

    def test_date_too_old(self) -> None:
        today = date.today()
        errors = validate(
            [self._ok_record(date=today - timedelta(days=366))],
            max_age_days=365,
            today=today,
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "date >= cutoff")

    def test_date_on_cutoff_boundary(self) -> None:
        today = date.today()
        # Exactly 365 days ago is still valid.
        errors = validate(
            [self._ok_record(date=today - timedelta(days=365))],
            max_age_days=365,
            today=today,
        )
        self.assertEqual(errors, [])

    def test_date_invalid_string(self) -> None:
        errors = validate([self._ok_record(date="not-a-date")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "valid date")

    def test_date_today_succeeds(self) -> None:
        errors = validate([self._ok_record(date=date.today())])
        self.assertEqual(errors, [])

    # ------------------------------------------------------------------
    # Rule 3: category must be one of the allowed set
    # ------------------------------------------------------------------
    def test_category_unknown(self) -> None:
        errors = validate([self._ok_record(category="entertainment")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "valid category")
        self.assertEqual(errors[0].value, "entertainment")

    def test_category_empty(self) -> None:
        errors = validate([self._ok_record(category="")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "valid category")

    def test_category_travel_ok(self) -> None:
        self.assertEqual(validate([self._ok_record(category="travel")]), [])

    def test_category_meal_ok(self) -> None:
        self.assertEqual(validate([self._ok_record(category="meal")]), [])

    def test_category_office_ok(self) -> None:
        self.assertEqual(validate([self._ok_record(category="office")]), [])

    def test_category_other_ok(self) -> None:
        self.assertEqual(validate([self._ok_record(category="other")]), [])

    # ------------------------------------------------------------------
    # Rule 4: note must be non-empty after stripping whitespace
    # ------------------------------------------------------------------
    def test_note_empty_string(self) -> None:
        errors = validate([self._ok_record(note="")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "non-empty note")

    def test_note_whitespace_only(self) -> None:
        errors = validate([self._ok_record(note="   \t\n  ")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "non-empty note")

    def test_note_none(self) -> None:
        errors = validate([self._ok_record(note=None)])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "non-empty note")

    def test_note_valid(self) -> None:
        self.assertEqual(validate([self._ok_record(note="coffee")]), [])

    # ------------------------------------------------------------------
    # Rule 5: currency must be CNY
    # ------------------------------------------------------------------
    def test_currency_usd(self) -> None:
        errors = validate([self._ok_record(currency="USD")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "currency == CNY")
        self.assertEqual(errors[0].value, "USD")

    def test_currency_empty(self) -> None:
        errors = validate([self._ok_record(currency="")])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "currency == CNY")

    def test_currency_cny_ok(self) -> None:
        self.assertEqual(validate([self._ok_record(currency="CNY")]), [])

    # ------------------------------------------------------------------
    # Multiple violations on the same record
    # ------------------------------------------------------------------
    def test_multiple_violations_same_record(self) -> None:
        bad = {
            "amount": -1,
            "date": "bad",
            "category": "fun",
            "note": "",
            "currency": "USD",
        }
        errors = validate([bad])
        rules = {e.rule for e in errors}
        self.assertEqual(rules, {
            "amount > 0",
            "valid date",
            "valid category",
            "non-empty note",
            "currency == CNY",
        })
        self.assertEqual(len(errors), 5)

    # ------------------------------------------------------------------
    # Line numbers are preserved
    # ------------------------------------------------------------------
    def test_line_numbers(self) -> None:
        records = [
            self._ok_record(line_number=10),
            self._ok_record(line_number=42, amount=-1),
        ]
        errors = validate(records)
        self.assertEqual({e.line_number for e in errors}, {42})
        self.assertTrue(all(e.line_number == 42 for e in errors))

    # ------------------------------------------------------------------
    # Clean record produces no errors
    # ------------------------------------------------------------------
    def test_clean_record(self) -> None:
        self.assertEqual(validate([self._ok_record()]), [])

    def test_multiple_clean_records(self) -> None:
        records = [self._ok_record(), self._ok_record(amount=20), self._ok_record(note="tip")]
        self.assertEqual(validate(records), [])


if __name__ == "__main__":
    unittest.main()
