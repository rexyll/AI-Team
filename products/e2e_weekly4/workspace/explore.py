import os
print("CWD:", os.getcwd())
print("--- root ---")
for item in sorted(os.listdir('.')):
    print(" ", item)
print("--- expense-reporter ---")
for item in sorted(os.listdir('expense-reporter')):
    path = os.path.join('expense-reporter', item)
    if os.path.isdir(path):
        print(" DIR:", item)
        for sub in sorted(os.listdir(path)):
            print("   ", sub)
    else:
        print(" FILE:", item)
