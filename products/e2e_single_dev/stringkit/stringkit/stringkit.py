def reverse(s: str) -> str:
    """反转字符串"""
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """判断字符串是否为回文（忽略大小写和非字母字符）"""
    cleaned = ''.join(ch.lower() for ch in s if ch.isalpha())
    return cleaned == cleaned[::-1]


def count_vowels(s: str) -> int:
    """统计字符串中的元音字母数量"""
    return sum(1 for ch in s.lower() if ch in 'aeiou')
