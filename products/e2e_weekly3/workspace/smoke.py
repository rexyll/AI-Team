import sys, os
# test_parser.py is at workspace root; expense-reporter is one level up from e2e_weekly3
script_dir = os.path.dirname(os.path.abspath(__file__))
root = script_dir
while root and not os.path.isdir(os.path.join(root, "expense-reporter")):
    parent = os.path.dirname(root)
    if parent == root:
        break
    root = parent
expense_root = os.path.join(root, "expense-reporter")
sys.path.insert(0, expense_root)
from expense_reporter.parser import parse_csv, CsvRecord, ParseError
print("import ok, module at:", expense_root)

import tempfile
content = "date,employee,category,amount,currency,note\n2024-01-15,Zhang San,Food,128.50,CNY,Lunch\n"
with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
    f.write(content)
    path = f.name
records, errors = parse_csv(path)
os.unlink(path)
assert len(records) == 1
assert len(errors) == 0
print("smoke test ok")
