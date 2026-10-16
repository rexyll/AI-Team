"""stringkit 核心函数的单元测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stringkit.stringops import reverse, is_palindrome, count_vowels


# ---------- reverse ----------

def test_reverse_basic():
    assert reverse("hello") == "olleh"


def test_reverse_empty():
    assert reverse("") == ""


def test_reverse_single_char():
    assert reverse("a") == "a"


def test_reverse_already_palindrome():
    assert reverse("aba") == "aba"


def test_reverse_pure_spaces():
    assert reverse("   ") == "   "


def test_reverse_mixed_non_alpha():
    assert reverse("a1!b@2") == "2@b!1a"


def test_reverse_numbers_only():
    assert reverse("12345") == "54321"


def test_reverse_symbol_only():
    assert reverse("abc") == "cba"


def test_reverse_all_same_char():
    assert reverse("aaaa") == "aaaa"


def test_reverse_unicode():
    assert reverse("中文") == "文中"


# ---------- is_palindrome ----------

def test_is_palindrome_simple():
    assert is_palindrome("aba") is True


def test_is_palindrome_case_insensitive():
    assert is_palindrome("AbBa") is True


def test_is_palindrome_with_spaces():
    assert is_palindrome("a b a") is True


def test_is_palindrome_not_palindrome():
    assert is_palindrome("hello") is False


def test_is_palindrome_empty():
    assert is_palindrome("") is True


def test_is_palindrome_numbers_only():
    assert is_palindrome("12321") is True


def test_is_palindrome_pure_spaces():
    assert is_palindrome("   ") is True


def test_is_palindrome_spaces_mixed():
    assert is_palindrome("A man a plan a canal Panama") is True


def test_is_palindrome_symbols_only():
    assert is_palindrome("!!!") is True


def test_is_palindrome_mixed_non_alpha():
    assert is_palindrome("a1a") is True


def test_is_palindrome_no_match():
    assert is_palindrome("abc") is False


def test_is_palindrome_single_char():
    assert is_palindrome("x") is True


# ---------- count_vowels ----------

def test_count_vowels_basic():
    assert count_vowels("hello") == 2


def test_count_vowels_all_vowels():
    assert count_vowels("aeiou") == 5


def test_count_vowels_case_insensitive():
    assert count_vowels("AEIOU") == 5


def test_count_vowels_mixed_case():
    assert count_vowels("aEiOu") == 5


def test_count_vowels_none():
    assert count_vowels("rhythm") == 0


def test_count_vowels_empty():
    assert count_vowels("") == 0


def test_count_vowels_with_spaces_and_consonants():
    assert count_vowels("Hello World") == 3


def test_count_vowels_pure_spaces():
    assert count_vowels("   ") == 0


def test_count_vowels_numbers_only():
    assert count_vowels("12345") == 0


def test_count_vowels_symbols_only():
    assert count_vowels("!@#$%") == 0


def test_count_vowels_all_consonants():
    assert count_vowels("bcdfg") == 0


def test_count_vowels_unicode():
    assert count_vowels("cafe") == 2


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
