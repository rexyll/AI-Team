# stringkit — 字符串工具库

一个简单的 Python 字符串处理工具库，提供反转、回文检测、元音计数等常用功能。

## 安装

```bash
pip install stringkit
```

或在项目根目录安装：

```bash
pip install -e .
```

## 函数说明

### `reverse(text: str) -> str`

反转字符串，返回输入字符串的逆序结果。

**用法示例：**

```python
from stringkit import reverse

reverse("hello")        # → "olleh"
reverse("ab!ba")        # → "ab!ba"
reverse("")             # → ""
reverse("a")            # → "a"
reverse("héllo")        # → "olléh"
```

**返回值：** 反转后的字符串（`str`）。

---

### `is_palindrome(text: str) -> bool`

检测字符串是否为回文。比较时忽略大小写和空格。

**用法示例：**

```python
from stringkit import is_palindrome

is_palindrome("aba")          # → True
is_palindrome("Abba")         # → True（忽略大小写）
is_palindrome("ab ba")        # → True（忽略空格）
is_palindrome("hello")        # → False
is_palindrome("")             # → True（空字符串视为回文）
is_palindrome("ab!ba")        # → True
```

**返回值：** 是回文返回 `True`，否则返回 `False`（`bool`）。

---

### `count_vowels(text: str) -> int`

统计字符串中元音字母（a, e, i, o, u，不区分大小写）的数量。

**用法示例：**

```python
from stringkit import count_vowels

count_vowels("hello")         # → 2（e, o）
count_vowels("HELLO")         # → 2
count_vowels("h3ll0!")        # → 0
count_vowels("")              # → 0
count_vowels("aeiou")         # → 5
count_vowels("AEIOU")         # → 5
```

**返回值：** 元音字母的数量（`int`）。
