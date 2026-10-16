"""stringkit - A simple string manipulation toolkit."""


def reverse(s: str) -> str:
    """Return the reversed string."""
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """Check if a string is a palindrome (case-sensitive)."""
    return s == s[::-1]


def count_vowels(s: str) -> int:
    """Count the number of vowels (a, e, i, o, u) in a string (case-insensitive)."""
    vowels = set('aeiouAEIOU')
    return sum(1 for char in s if char in vowels)