import os
import sys

print("Working directory:", os.getcwd())
print("\nRoot level files:")
for item in os.listdir('.'):
    full_path = os.path.abspath(item)
    if os.path.isdir(full_path):
        print(f"  [DIR] {item}/")
        for sub in os.listdir(item):
            print(f"    {sub}")
    else:
        print(f"  {item}")
