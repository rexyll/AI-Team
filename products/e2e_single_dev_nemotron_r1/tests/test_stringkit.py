"""Tests for stringkit package."""

import pytest
import stringkit


class TestReverse:
    def test_reverse_empty_string(self):
        assert stringkit.reverse("") == ""

    def test_reverse_single_char(self):
        assert stringkit.reverse("a") == "a"

    def test_reverse_normal_string(self):
        assert stringkit.reverse("hello") == "olleh"

    def test_reverse_with_spaces(self):
        assert stringkit.reverse("hello world") == "dlrow olleh"

    def test_reverse_unicode(self):
        assert stringkit.reverse("你好") == "好你"


class TestIsPalindrome:
    def test_empty_string_is_palindrome(self):
        assert stringkit.is_palindrome("") is True

    def test_single_char_is_palindrome(self):
        assert stringkit.is_palindrome("a") is True

    def test_palindrome_even_length(self):
        assert stringkit.is_palindrome("abba") is True

    def test_palindrome_odd_length(self):
        assert stringkit.is_palindrome("aba") is True

    def test_non_palindrome(self):
        assert stringkit.is_palindrome("hello") is False

    def test_case_sensitive(self):
        assert stringkit.is_palindrome("Abba") is False


class TestCountVowels:
    def test_empty_string(self):
        assert stringkit.count_vowels("") == 0

    def test_no_vowels(self):
        assert stringkit.count_vowels("bcdfg") == 0

    def test_all_vowels_lowercase(self):
        assert stringkit.count_vowels("aeiou") == 5

    def test_all_vowels_uppercase(self):
        assert stringkit.count_vowels("AEIOU") == 5

    def test_mixed_case(self):
        assert stringkit.count_vowels("Hello World") == 3

    def test_with_numbers_and_symbols(self):
        assert stringkit.count_vowels("h3llo!") == 1