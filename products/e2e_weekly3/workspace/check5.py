import sys
import os
print("cwd:", os.getcwd())
print("script dir:", os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace", "expense-reporter")
print("added path:", path)
sys.path.insert(0, path)
print("sys.path[0]:", sys.path[0])
try:
    import expense_reporter
    print("import ok:", expense_reporter)
except Exception as e:
    print("import error:", e)
