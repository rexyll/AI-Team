"""Test runner for csv_parser module."""

import sys
import os

# Add the workspace root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import io
from decimal import Decimal
from datetime import date

from expense_reporter.csv_parser import parse_csv, ParseError, REQUIRED_COLUMNS
from expense_reporter.models import ExpenseRecord


def test_basic_parsing():
    """Test basic CSV parsing with valid rows."""
    csv_content = """date,employee,category,amount,currency,note
2024-01-15,Alice Smith,Travel,1500.50,USD,Flight to NYC
2024-01-16,Bob Jones,Meals,45.00,USD,Client lunch
"""
    records, errors = parse_csv(csv_content)
    assert len(errors) == 0
    assert len(records) == 2

    assert records[0] == ExpenseRecord(
        date=date(2024, 1, 15),
        employee="Alice Smith",
        category="Travel",
        amount=Decimal("1500.50"),
        currency="USD",
        note="Flight to NYC",
    )
    assert records[1] == ExpenseRecord(
        date=date(2024, 1, 16),
        employee="Bob Jones",
        category="Meals",
        amount=Decimal("45.00"),
        currency="USD",
        note="Client lunch",
    )


def test_bom_handling():
    """Test that BOM is handled correctly."""
    csv_content = "\ufeffdate,employee,category,amount,currency,note\n2024-01-15,Alice,Travel,100,USD,Test"
    records, errors = parse_csv(csv_content)
    assert len(errors) == 0
    assert len(records) == 1
    assert records[0].employee == "Alice"


def test_missing_columns():
    """Test error when required columns are missing."""
    csv_content = """date,employee,category
2024-01-15,Alice,Travel
"""
    records, errors = parse_csv(csv_content)
    assert len(records) == 0
    assert len(errors) == 1
    assert "currency" in errors[0].reason.lower() or "Missing" in errors[0].reason


def test_bad_row_count():
    """Test that rows with wrong number of fields generate ParseError."""
    csv_content = """date,employee,category,amount,currency,note
2024-01-15,Alice,Travel,100,USD,Note,extra_field
2024-01-16,Bob,Meals,50
"""
    records, errors = parse_csv(csv_content)
    assert len(records) == 0
    assert len(errors) == 2
    assert errors[0].row_number == 2
    assert "6 fields" in errors[0].reason
    assert errors[1].row_number == 3
    assert "6 fields" in errors[1].reason


def test_invalid_date():
    """Test that invalid dates generate ParseError."""
    csv_content = """date,employee,category,amount,currency,note
not-a-date,Alice,Travel,100,USD,Note
"""
    records, errors = parse_csv(csv_content)
    assert len(records) == 0
    assert len(errors) == 1
    assert errors[0].row_number == 2
    assert "Invalid date" in errors[0].reason


def test_invalid_amount():
    """Test that invalid amounts generate ParseError."""
    csv_content = """date,employee,category,amount,currency,note
2024-01-15,Alice,Travel,abc,USD,Note
"""
    records, errors = parse_csv(csv_content)
    assert len(records) == 0
    assert len(errors) == 1
    assert errors[0].row_number == 2
    assert "Invalid amount" in errors[0].reason


def test_mixed_good_and_bad_rows():
    """Test that processing continues after errors."""
    csv_content = """date,employee,category,amount,currency,note
2024-01-15,Alice,Travel,1500.50,USD,Flight
not-a-date,Bob,Meals,45,USD,Bad date
2024-01-17,Charlie,Office,200,USD,Supplies
"""
    records, errors = parse_csv(csv_content)
    assert len(records) == 2
    assert len(errors) == 1
    assert errors[0].row_number == 3
    assert records[0].employee == "Alice"
    assert records[1].employee == "Charlie"


def test_empty_csv():
    """Test empty CSV file."""
    records, errors = parse_csv("")
    assert len(records) == 0
    assert len(errors) == 1
    assert "Empty" in errors[0].reason


def test_header_only():
    """Test CSV with only header row."""
    csv_content = "date,employee,category,amount,currency,note"
    records, errors = parse_csv(csv_content)
    assert len(records) == 0
    assert len(errors) == 0


def test_whitespace_trimming():
    """Test that whitespace is trimmed from fields."""
    csv_content = """date,employee,category,amount,currency,note
  2024-01-15 , Alice , Travel , 100.00 , USD , Note  
"""
    records, errors = parse_csv(csv_content)
    assert len(errors) == 0
    assert records[0].employee == "Alice"
    assert records[0].note == "Note"


def test_negative_amount():
    """Test negative amounts are handled."""
    csv_content = """date,employee,category,amount,currency,note
2024-01-15,Alice,Refund,-50.00,USD,Return
"""
    records, errors = parse_csv(csv_content)
    assert len(errors) == 0
    assert records[0].amount == Decimal("-50.00")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
