import sys
import os
# test_parser.py is in the workspace root; expense_reporter is in workspace/expense-reporter
script_dir = os.path.dirname(os.path.abspath(__file__))
# Walk up to find the actual root (could be workspace or e2e_weekly3)
root = script_dir
while root and not os.path.isdir(os.path.join(root, "expense-reporter")):
    parent = os.path.dirname(root)
    if parent == root:
        break
    root = parent

expense_root = os.path.join(root, "expense-reporter")
sys.path.insert(0, expense_root)

from expense_reporter.parser import parse_csv, CsvRecord, ParseError
import tempfile


def test_basic_csv():
    content = """date,employee,category,amount,currency,note
2024-01-15,Zhang San,Food,128.50,CNY,Lunch
2024-01-16,Li Si,Transport,32.00,CNY,Taxi
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 2
    assert len(errors) == 0
    assert records[0].date == "2024-01-15"
    assert records[0].amount == "128.50"
    assert records[0].currency == "CNY"


def test_utf8_bom():
    content = "date,employee,category,amount,currency,note\n2024-01-15,Zhang San,Food,128.50,CNY,Note\n"
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(b"\xef\xbb\xbf")
        f.write(content.encode("utf-8"))
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 1
    assert records[0].date == "2024-01-15"
    assert len(errors) == 0


def test_missing_columns():
    content = """employee,category,amount
Zhang San,Food,128.50
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 1
    assert "missing required columns" in errors[0].reason


def test_field_count_mismatch():
    content = """date,employee,category,amount,currency,note
2024-01-15,Zhang San
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 1
    assert "field count mismatch" in errors[0].reason


def test_invalid_date():
    content = """date,employee,category,amount,currency,note
2024-13-01,Zhang San,Food,128.50,CNY,Note
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 1
    assert "invalid date format" in errors[0].reason


def test_invalid_amount():
    content = """date,employee,category,amount,currency,note
2024-01-15,Zhang San,Food,128,CNY,Note
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 1
    assert "invalid amount format" in errors[0].reason


def test_invalid_currency():
    content = """date,employee,category,amount,currency,note
2024-01-15,Zhang San,Food,128.50,USD,Note
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 1
    assert "unsupported currency" in errors[0].reason


def test_good_and_bad_rows():
    content = """date,employee,category,amount,currency,note
2024-01-15,Zhang San,Food,128.50,CNY,Lunch
2024-13-01,Bad Date,Food,128.50,CNY,Bad
2024-01-16,Li Si,Transport,32.00,CNY,Taxi
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 2
    assert len(errors) == 1
    assert records[0].employee == "Zhang San"
    assert records[1].employee == "Li Si"


def test_extra_columns_ignored():
    content = """date,employee,category,amount,currency,note,extra
2024-01-15,Zhang San,Food,128.50,CNY,Note,ignored
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 1
    assert len(errors) == 0


def test_empty_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("")
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 0


def test_header_only():
    content = """date,employee,category,amount,currency,note
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, errors = parse_csv(path)
    os.unlink(path)
    assert len(records) == 0
    assert len(errors) == 0


if __name__ == "__main__":
    for name, obj in list(globals().items()):
        if name.startswith("test_") and callable(obj):
            try:
                obj()
                print(f"PASS: {name}")
            except Exception as e:
                print(f"FAIL: {name} - {e}")
