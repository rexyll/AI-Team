# stringkit

A simple string manipulation toolkit for Python.

## Installation

```bash
pip install -e .
```

## Usage

```python
import stringkit

# Reverse a string
stringkit.reverse("hello")  # "olleh"

# Check if a string is a palindrome
stringkit.is_palindrome("aba")   # True
stringkit.is_palindrome("hello") # False

# Count vowels in a string
stringkit.count_vowels("hello world")  # 3
```

## Functions

### `reverse(s: str) -> str`
Returns the reversed string.

### `is_palindrome(s: str) -> bool`
Checks if a string is a palindrome (case-sensitive).

### `count_vowels(s: str) -> int`
Counts the number of vowels (a, e, i, o, u) in a string (case-insensitive).

## Testing

```bash
pytest
```