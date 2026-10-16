import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stringkit import reverse, is_palindrome, count_vowels


# ─── reverse ─────────────────────────────────────────────────────────────────

class TestReverse:
    def test_normal_string(self):
        assert reverse("hello") == "olleh"

    def test_empty_string(self):
        assert reverse("") == ""

    def test_single_char(self):
        assert reverse("a") == "a"

    def test_two_chars(self):
        assert reverse("ab") == "ba"

    def test_already_palindrome(self):
        assert reverse("racecar") == "racecar"

    def test_unicode(self):
        assert reverse("你好") == "好你"

    def test_mixed_language(self):
        assert reverse("abc中文") == "文中cba"

    def test_special_characters(self):
        assert reverse("!@#$%") == "%$#@!"

    def test_whitespace(self):
        assert reverse("a b c") == "c b a"

    def test_numbers(self):
        assert reverse("12345") == "54321"

    def test_emoji(self):
        assert reverse("😀😃😄") == "😄😃😀"

    def test_mixed_ascii_and_special(self):
        assert reverse("Hello, World!") == "!dlroW ,olleH"

    def test_newline(self):
        assert reverse("ab\ncd") == "dc\nba"

    def test_tab(self):
        assert reverse("a\tb") == "b\ta"


# ─── is_palindrome ────────────────────────────────────────────────────────────

class TestIsPalindrome:
    def test_basic_palindrome(self):
        assert is_palindrome("racecar") is True

    def test_basic_non_palindrome(self):
        assert is_palindrome("hello") is False

    def test_case_insensitive(self):
        assert is_palindrome("Racecar") is True

    def test_with_spaces(self):
        assert is_palindrome("Race Car") is True
        assert is_palindrome("A man a plan a canal Panama") is True

    def test_empty_string(self):
        assert is_palindrome("") is True

    def test_single_char(self):
        assert is_palindrome("a") is True

    def test_two_same_chars(self):
        assert is_palindrome("aa") is True

    def test_two_different_chars(self):
        assert is_palindrome("ab") is False

    def test_unicode_palindrome(self):
        assert is_palindrome("上海自来水来自海上") is True

    def test_unicode_non_palindrome(self):
        assert is_palindrome("你好世界") is False

    def test_special_chars_no_spaces(self):
        assert is_palindrome("aba") is True
        # "ab!ba" 去掉空格后为 "ab!ba"，反转后仍为 "ab!ba"，是回文
        assert is_palindrome("ab!ba") is True

    def test_only_spaces(self):
        assert is_palindrome("   ") is True

    def test_mixed_case_and_spaces(self):
        assert is_palindrome("Ab Ba") is True

    def test_numeric_string(self):
        assert is_palindrome("12321") is True
        assert is_palindrome("12345") is False

    def test_emoji_palindrome(self):
        assert is_palindrome("😀😃😀") is True
        assert is_palindrome("😀😃😄") is False


# ─── count_vowels ─────────────────────────────────────────────────────────────

class TestCountVowels:
    def test_hello(self):
        assert count_vowels("hello") == 2

    def test_all_vowels_upper(self):
        assert count_vowels("AEIOU") == 5

    def test_empty_string(self):
        assert count_vowels("") == 0

    def test_no_vowels(self):
        assert count_vowels("rhythm") == 0

    def test_mixed_case(self):
        assert count_vowels("aEiOu") == 5

    def test_single_vowel(self):
        assert count_vowels("a") == 1

    def test_single_consonant(self):
        assert count_vowels("b") == 0

    def test_all_consonants(self):
        assert count_vowels("bcdfg") == 0

    def test_vowels_with_numbers_and_special(self):
        # "h3ll0!" 中不含任何元音字母（a/e/i/o/u）
        assert count_vowels("h3ll0!") == 0

    def test_whitespace_only(self):
        assert count_vowels("   ") == 0

    def test_unicode(self):
        assert count_vowels("你好世界") == 0

    def test_spanish_vowels(self):
        assert count_vowels("áéíóú") == 0  # accents not counted by current impl

    def test_tab_and_newline(self):
        assert count_vowels("a\nb\nc") == 1


if __name__ == "__main__":
    test_reverse = TestReverse()
    test_is_palindrome = TestIsPalindrome()
    test_count_vowels = TestCountVowels()

    for obj in [test_reverse, test_is_palindrome, test_count_vowels]:
        for name in dir(obj):
            if name.startswith("test_"):
                getattr(obj, name)()
    print("All tests passed.")
