"""stringkit 单元测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stringkit import reverse, is_palindrome, count_vowels


class TestReverse:
    def test_basic(self):
        assert reverse("hello") == "olleh"

    def test_empty(self):
        assert reverse("") == ""

    def test_single_char(self):
        assert reverse("a") == "a"

    def test_already_palindrome(self):
        assert reverse("abba") == "abba"


class TestIsPalindrome:
    def test_simple_palindrome(self):
        assert is_palindrome("racecar") is True

    def test_not_palindrome(self):
        assert is_palindrome("hello") is False

    def test_ignore_case(self):
        assert is_palindrome("Racecar") is True

    def test_ignore_spaces(self):
        assert is_palindrome("A man a plan a canal Panama") is True

    def test_empty(self):
        assert is_palindrome("") is True

    def test_single_char(self):
        assert is_palindrome("a") is True


class TestCountVowels:
    def test_basic(self):
        assert count_vowels("hello") == 2

    def test_all_vowels(self):
        assert count_vowels("aeiou") == 5

    def test_uppercase(self):
        assert count_vowels("AEIOU") == 5

    def test_mixed_case(self):
        assert count_vowels("AeIoU") == 5

    def test_no_vowels(self):
        assert count_vowels("rhythm") == 0

    def test_empty(self):
        assert count_vowels("") == 0

    def test_consonants_only(self):
        assert count_vowels("bcdfg") == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
