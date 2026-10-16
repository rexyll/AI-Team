"""stringkit 核心函数实现"""


def reverse(s: str) -> str:
    """返回反转字符串"""
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """忽略大小写和空格判断是否为回文"""
    cleaned = s.replace(" ", "").lower()
    return cleaned == cleaned[::-1]


def count_vowels(s: str) -> int:
    """统计元音字母（a,e,i,o,u，大小写均计）个数"""
    return sum(1 for ch in s if ch.lower() in "aeiou")
