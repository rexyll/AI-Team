import os
# Check for any config files
for name in ['pyproject.toml', 'setup.py', 'setup.cfg', 'pytest.ini', 'requirements.txt', '.gitignore']:
    try:
        with open(name) as f:
            print(f'{name}: {repr(f.read()[:200])}')
    except:
        print(f'{name}: NOT FOUND')

# Check expense-reporter for any hidden files
print('\nexpense-reporter contents (all):')
for item in os.listdir('expense-reporter'):
    print(f'  {repr(item)}')
