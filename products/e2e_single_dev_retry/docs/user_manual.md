

# stringkit 用户手册

## 一、功能简介

`stringkit` 是一个轻量级 Python 字符串处理工具包，提供三个纯函数，无需安装额外依赖即可使用。

| 函数 | 功能描述 |
|------|----------|
| `reverse(s)` | 反转输入字符串，返回新字符串 |
| `is_palindrome(s)` | 忽略大小写和空格，判断字符串是否为回文 |
| `count_vowels(s)` | 统计字符串中元音字母（a, e, i, o, u）的出现次数 |

---

## 二、快速上手

### 安装

```bash
pip install stringkit
```

或直接使用源码：

```python
from stringkit import reverse, is_palindrome, count_vowels
```

### 基本使用示例

```python
>>> from stringkit import reverse, is_palindrome, count_vowels

>>> reverse("abc")
'cba'

>>> reverse("")
''

>>> is_palindrome("Aba")
True

>>> is_palindrome("Never odd or even")
True

>>> count_vowels("hello")
2

>>> count_vowels("AEIOU")
5
```

---

## 三、函数详细说明

### 3.1 reverse(s)

**功能**：反转输入字符串，返回新字符串。

**参数**：
- `s` (str)：待反转的字符串

**返回值**：
- (str)：反转后的字符串

**示例**：

```python
>>> reverse("hello")
'olleh'

>>> reverse("abc")
'cba'

>>> reverse("")
''

>>> reverse("a")
'a'
```

---

### 3.2 is_palindrome(s)

**功能**：忽略大小写和空格，判断字符串是否为回文。

**参数**：
- `s` (str)：待检测的字符串

**返回值**：
- (bool)：如果是回文返回 `True`，否则返回 `False`

**示例**：

```python
>>> is_palindrome("Aba")
True

>>> is_palindrome("racecar")
True

>>> is_palindrome("hello")
False

>>> is_palindrome("Never odd or even")
True
```

---

### 3.3 count_vowels(s)

**功能**：统计字符串中元音字母（a, e, i, o, u）的出现次数，大小写均计入。

**参数**：
- `s` (str)：待统计的字符串

**返回值**：
- (int)：元音字母出现的次数

**示例**：

```python
>>> count_vowels("hello")
2

>>> count_vowels("bcdfg")
0

>>> count_vowels("AEIOU")
5
```

---

## 四、常见问题 FAQ

**Q1：支持哪些 Python 版本？**  
A：支持 Python 3.7 及以上版本。

**Q2：`is_palindrome` 是否区分大小写？**  
A：不区分大小写。例如 `"Aba"` 会被识别为回文，返回 `True`。

**Q3：`is_palindrome` 是否忽略空格？**  
A：是的。例如 `"Never odd or even"` 会被识别为回文，返回 `True`。

**Q4：`count_vowels` 是否统计大写元音？**  
A：是的，大小写均计入。例如 `"AEIOU"` 返回 `5`。

**Q5：`y` / `Y` 是否算作元音字母？**  
A：不算。元音字母仅包含 a, e, i, o, u。

**Q6：输入非字符串类型会怎样？**  
A：本工具包假设输入均为字符串类型，未对非字符串输入做类型转换或错误处理。

---

*文档版本：v1.0*  
*最后更新：2026年*