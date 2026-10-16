"""stringkit - A simple string manipulation toolkit."""


def reverse(s: str) -> str:
    """Return the reversed string.

    Args:
        s: The input string.

    Returns:
        The reversed string.

    Examples:
        >>> reverse("hello")
        'olleh'
        >>> reverse("")
        ''
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected str, got {type(s).__name__}")
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """Check if a string is a palindrome, ignoring case and spaces.

    Args:
        s: The input string.

    Returns:
        True if the string is a palindrome (ignoring case and spaces), False otherwise.

    Examples:
        >>> is_palindrome("A man a plan a canal Panama")
        True
        >>> is_palindrome("racecar")
        True
        >>> is_palindrome("hello")
        False
        >>> is_palindrome("")
        True
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected str, got {type(s).__name__}")
    # Remove spaces and convert to lowercase
    cleaned = s.replace(" ", "").lower()
    return cleaned == cleaned[::-1]


def count_vowels(s: str) -> int:
    """Count the number of vowels (a, e, i, o, u) in a string, case-insensitive.

    Args:
        s: The input string.

    Returns:
        The count of vowels in the string.

    Examples:
        >>> count_vowels("hello")
        2
        >>> count_vowels("HELLO")
        2
        >>> count_vowels("xyz")
        0
        >>> count_vowels("")
        0
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected str, got {type(s).__name__}")
    vowels = set("aeiou")
    return sum(1 for char in s.lower() if char in vowels)


if __name__ == "__main__":
    # Simple manual test
    print(reverse("hello"))  # olleh
    print(is_palindrome("A man a plan a canal Panama"))  # True
    print(count_vowels("hello"))  # 2