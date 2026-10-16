import os
# List expense-reporter contents
try:
    contents = os.listdir('expense-reporter')
    print('expense-reporter contents:', repr(contents))
except Exception as e:
    print('Error:', e)

# Check if workspace dir exists
try:
    contents2 = os.listdir('workspace')
    print('workspace contents:', repr(contents2))
except Exception as e:
    print('workspace error:', e)

# List all directories from root
for root, dirs, files in os.walk('.'):
    print(f'[{root}] files={files}')
