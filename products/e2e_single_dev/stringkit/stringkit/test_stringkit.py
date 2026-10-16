import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from stringkit import reverse, is_palindrome, count_vowels


class TestReverse(unittest.TestCase):
    def test_normal_string(self):
        self.assertEqual(reverse("hello"), "olleh")

    def test_empty_string(self):
        self.assertEqual(reverse(""), "")

    def test_single_char(self):
        self.assertEqual(reverse("a"), "a")

    def test_pure_spaces(self):
        self.assertEqual(reverse("   "), "   ")

    def test_mixed_case(self):
        self.assertEqual(reverse("AbCd"), "dCbA")

    def test_non_alpha_chars(self):
        self.assertEqual(reverse("a1!b"), "b!1a")


class TestIsPalindrome(unittest.TestCase):
    def test_normal_palindrome(self):
        self.assertTrue(is_palindrome("racecar"))

    def test_mixed_case_palindrome(self):
        self.assertTrue(is_palindrome("RaceCar"))

    def test_not_palindrome(self):
        self.assertFalse(is_palindrome("hello"))

    def test_empty_string(self):
        self.assertTrue(is_palindrome(""))

    def test_pure_spaces(self):
        self.assertTrue(is_palindrome("   "))

    def test_with_non_alpha_chars(self):
        self.assertTrue(is_palindrome("A man, a plan, a canal: Panama"))
        self.assertFalse(is_palindrome("abc!"))

    def test_single_char(self):
        self.assertTrue(is_palindrome("a"))

    def test_numbers_only(self):
        # 无字母字符视为空字符串，是回文
        self.assertTrue(is_palindrome("123"))


class TestCountVowels(unittest.TestCase):
    def test_normal_string(self):
        self.assertEqual(count_vowels("hello"), 2)

    def test_empty_string(self):
        self.assertEqual(count_vowels(""), 0)

    def test_no_vowels(self):
        self.assertEqual(count_vowels("rhythm"), 0)

    def test_pure_spaces(self):
        self.assertEqual(count_vowels("   "), 0)

    def test_mixed_case(self):
        self.assertEqual(count_vowels("AEIOU"), 5)
        self.assertEqual(count_vowels("aEiOu"), 5)

    def test_non_alpha_chars(self):
        self.assertEqual(count_vowels("h3ll0!"), 0)

    def test_all_vowels(self):
        self.assertEqual(count_vowels("aeiou"), 5)


if __name__ == "__main__":
    unittest.main()
