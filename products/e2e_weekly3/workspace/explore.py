import os
with open('explore.txt', 'w', encoding='utf-8') as f:
    for root, dirs, files in os.walk('.'):
        level = root.replace('.', '').count(os.sep)
        indent = ' ' * 2 * level
        f.write(f'{indent}[{os.path.basename(root)}/]\n')
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            f.write(f'{subindent}{file}\n')
print('Done')
