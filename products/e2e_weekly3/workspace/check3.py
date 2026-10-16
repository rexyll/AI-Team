import os
# Check all files in expense-reporter including hidden
for root, dirs, files in os.walk('expense-reporter'):
    for f in files:
        path = os.path.join(root, f)
        print(path)
    for d in dirs:
        print(f'[{os.path.join(root, d)}]')

# Also check parent
print('\nParent dir:', os.listdir('..') if os.path.exists('..') else 'N/A')
print('Root listdir:', os.listdir('.'))
