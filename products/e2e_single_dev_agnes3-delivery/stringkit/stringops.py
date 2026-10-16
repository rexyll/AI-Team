"""字符串处理核心函数"""


def reverse(s: str) -> str:
    """反转字符串。

    Args:
        s: 待反转的原始字符串。

    Returns:
        反转后的新字符串。
    """
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """判断字符串是否为回文（忽略大小写和空格）。

    Args:
        s: 待检测的字符串。

    Returns:
        若是回文返回 True，否则返回 False。
    """
    cleaned = s.replace(" ", "").lower()
    return cleaned == cleaned[::-1]


def count_vowels(s: str) -> int:
    """统计字符串中元音字母的个数（大小写均计入）。

    Args:
        s: 待统计的字符串。

    Returns:
        元音字母总个数。
    """
    vowels = set("aeiouAEIOU")
    return sum(1 for ch in s if ch in vowels)
