# stringkit 使用示例

## 安装

```bash
pip install -e .
```

## 函数说明

### reverse(s: str) -> str

反转字符串。

```python
>>> from stringkit import reverse
>>> reverse("hello")
'olleh'
```

### is_palindrome(s: str) -> bool

判断字符串是否为回文，忽略大小写和非字母字符。

```python
>>> from stringkit import is_palindrome
>>> is_palindrome("RaceCar")
True
>>> is_palindrome("A man, a plan, a canal: Panama")
True
```

### count_vowels(s: str) -> int

统计字符串中元音字母（a, e, i, o, u）的数量，不区分大小写。

```python
>>> from stringkit import count_vowels
>>> count_vowels("hello")
2
>>> count_vowels("AEIOU")
5
```

## 运行测试

```bash
python -m pytest stringkit/stringkit/test_stringkit.py -v
```
