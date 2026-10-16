# stringkit

简洁的字符串处理工具包，提供三个纯函数。

## 安装

```bash
pip install -e .
```

## 函数说明

### `reverse(s: str) -> str`

反转字符串。

**示例：**
```python
>>> from stringkit import reverse
>>> reverse("hello")
'olleh'
>>> reverse("")
''
```

---

### `is_palindrome(s: str) -> bool`

判断字符串是否为回文（**忽略大小写和空格**）。

**示例：**
```python
>>> from stringkit import is_palindrome
>>> is_palindrome("aba")
True
>>> is_palindrome("AbBa")
True
>>> is_palindrome("a b a")
True
>>> is_palindrome("hello")
False
```

**注意事项：**
- 空格会被移除后比较，因此 `"race car"` 也被视为回文。
- 大小写不敏感，`"Madam"` 视为回文。
- 空字符串视为回文（返回 `True`）。

---

### `count_vowels(s: str) -> int`

统计字符串中元音字母（a, e, i, o, u，大小写均计入）的个数。

**示例：**
```python
>>> from stringkit import count_vowels
>>> count_vowels("hello")
2
>>> count_vowels("AEIOU")
5
>>> count_vowels("rhythm")
0
```

**注意事项：**
- 只统计英文元音字母 `a e i o u A E I O U`，不涉及 y。
- 空格、数字及其他字符不计入。

## 运行测试

```bash
python -m pytest stringkit/tests/test_stringops.py -v
```
