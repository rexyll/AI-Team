"""Tests for expense_reporter.csv_parser (REQ-001)."""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expense_reporter.csv_parser import ParseError, parse_csv  # noqa: E402
from expense_reporter.models import ExpenseRecord  # noqa: E402


class TestParseCsv(unittest.TestCase):
    """Cover CSV parsing: good rows, bad rows, BOM, missing columns, etc."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_csv(self, rows: list[list[str]], with_bom: bool = False) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(rows)
        content = buf.getvalue()
        if with_bom:
            content = "\ufeff" + content
        return content.encode("utf-8")

    def _parse(self, content: bytes, **kwargs) -> tuple[list, list]:
        fh = io.BytesIO(content)
        return parse_csv(fh, **kwargs)

    # ------------------------------------------------------------------
    # Happy path: clean CSV
    # ------------------------------------------------------------------
    def test_basic_good_rows(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice", "meal", "25.50", "CNY", "lunch"],
            ["2024-02-20", "Bob", "travel", "500.00", "CNY", "flight"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].date, date(2024, 1, 15))
        self.assertEqual(records[0].amount, 25.50)
        self.assertEqual(records[0].raw["employee"], "Alice")
        self.assertEqual(records[0].category, "meal")
        self.assertEqual(records[0].note, "lunch")
        self.assertEqual(records[0].currency, "CNY")
        self.assertEqual(records[0].line_number, 2)

    # ------------------------------------------------------------------
    # BOM handling
    # ------------------------------------------------------------------
    def test_bom(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-03-01", "Carol", "office", "10.00", "CNY", "pens"],
        ], with_bom=True)
        records, errors = self._parse(content)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].date, date(2024, 3, 1))

    # ------------------------------------------------------------------
    # Extra columns are ignored
    # ------------------------------------------------------------------
    def test_extra_columns_ignored(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note", "extra"],
            ["2024-01-15", "Alice", "meal", "25.50", "CNY", "lunch", "ignored"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].raw.get("extra"), "ignored")

    # ------------------------------------------------------------------
    # Bad rows → ParseError list
    # ------------------------------------------------------------------
    def test_bad_date_format(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["15-01-2024", "Alice", "meal", "25.50", "CNY", "lunch"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ParseError)
        self.assertEqual(errors[0].line_number, 2)
        self.assertIn("date", errors[0].reason)

    def test_bad_amount_format(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice", "meal", "25.5", "CNY", "lunch"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line_number, 2)
        self.assertIn("amount", errors[0].reason)

    def test_bad_amount_integer(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice", "meal", "25", "CNY", "lunch"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line_number, 2)

    def test_bad_currency(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice", "meal", "25.50", "USD", "lunch"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line_number, 2)
        self.assertIn("currency", errors[0].reason)

    def test_missing_required_column(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount"],
            ["2024-01-15", "Alice", "meal", "25.50"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertGreaterEqual(len(errors), 1)
        # Should have at least one header error
        header_errors = [e for e in errors if e.line_number == 1]
        self.assertGreater(len(header_errors), 0)
        self.assertIn("missing", header_errors[0].reason)

    def test_mixed_good_and_bad_rows(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice", "meal", "25.50", "CNY", "lunch"],      # row 2 – good
            ["bad-date", "Bob", "travel", "500.00", "CNY", "flight"],       # row 3 – bad date
            ["2024-03-01", "Carol", "office", "10.00", "CNY", "pens"],     # row 4 – good
            ["2024-04-01", "Dave", "meal", "abc", "CNY", "coffee"],        # row 5 – bad amount
            ["2024-05-01", "Eve", "travel", "100.00", "USD", "ticket"],    # row 6 – bad currency
        ])
        records, errors = self._parse(content)
        # 2 good rows
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].raw["employee"], "Alice")
        self.assertEqual(records[1].raw["employee"], "Carol")
        # 3 bad rows
        self.assertEqual(len(errors), 3)
        error_lines = {e.line_number for e in errors}
        self.assertEqual(error_lines, {3, 5, 6})

    def test_empty_file(self) -> None:
        content = b""
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].reason, "empty file")

    def test_header_only(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 0)

    def test_short_row_missing_fields(self) -> None:
        """A row with fewer fields than the header → missing-field error."""
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice"],  # only 2 fields; amount/currency/note missing
        ])
        records, errors = self._parse(content)
        self.assertEqual(len(records), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line_number, 2)
        self.assertIn("missing", errors[0].reason)

    # ------------------------------------------------------------------
    # Path input (file on disk)
    # ------------------------------------------------------------------
    def test_parse_from_path(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", encoding="utf-8-sig", newline="", delete=False
        ) as tmp:
            writer = csv.writer(tmp)
            writer.writerow(["date", "employee", "category", "amount", "currency", "note"])
            writer.writerow(["2024-01-15", "Alice", "meal", "25.50", "CNY", "lunch"])
            tmp_path = tmp.name
        try:
            records, errors = parse_csv(tmp_path)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].raw["employee"], "Alice")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Row numbering is correct
    # ------------------------------------------------------------------
    def test_line_numbers(self) -> None:
        content = self._make_csv([
            ["date", "employee", "category", "amount", "currency", "note"],
            ["2024-01-15", "Alice", "meal", "25.50", "CNY", "lunch"],
            ["2024-02-20", "Bob", "travel", "500.00", "CNY", "flight"],
        ])
        records, _ = self._parse(content)
        self.assertEqual(records[0].line_number, 2)
        self.assertEqual(records[1].line_number, 3)


if __name__ == "__main__":
    unittest.main()
