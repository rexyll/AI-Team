import os
for root, dirs, files in os.walk('workspace'):
    for f in files:
        print(os.path.join(root, f))
    for d in dirs:
        print(f'[{os.path.join(root, d)}/]')
