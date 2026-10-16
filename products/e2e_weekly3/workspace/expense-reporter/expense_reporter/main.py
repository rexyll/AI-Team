from .parser import parse_csv

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m expense_reporter <csv_file>", file=sys.stderr)
        sys.exit(1)
    records, errors = parse_csv(sys.argv[1])
    print(f"Valid records: {len(records)}")
    print(f"Parse errors: {len(errors)}")
    for err in errors:
        print(f"  Row {err.row_num}: {err.reason}")
