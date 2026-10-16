def reverse(s: str) -> str:
    """返回字符串的反转。"""
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """
    判断字符串是否回文。
    判断前去除所有空格并统一转为小写。
    """
    cleaned = s.replace(" ", "").lower()
    return cleaned == cleaned[::-1]


def count_vowels(s: str) -> int:
    """
    统计字符串中元音字母（a、e、i、o、u）的个数，不区分大小写。
    """
    vowels = set("aeiouAEIOU")
    return sum(1 for ch in s if ch in vowels)
