

# stringkit 用户手册

## 1. 产品简介

`stringkit` 是一个纯 Python 字符串处理工具包，提供三个常用字符串操作函数。该工具包无任何第三方依赖，可直接通过 `pip` 安装后使用。

**核心功能**：
| 函数 | 描述 | 返回类型 |
|------|------|----------|
| `reverse(s)` | 返回字符串的反转 | `str` |
| `is_palindrome(s)` | 判断字符串是否回文（忽略大小写和空格） | `bool` |
| `count_vowels(s)` | 统计字符串中元音字母（a/e/i/o/u）的个数 | `int` |

---

## 2. 快速上手

### 2.1 安装

```bash
pip install stringkit
```

### 2.2 导入函数

```python
from stringkit import reverse, is_palindrome, count_vowels
```

### 2.3 最小示例

```python
print(reverse("hello"))           # 输出: olleh
print(is_palindrome("Madam"))     # 输出: True
print(count_vowels("hello"))      # 输出: 2
```

---

## 3. 功能详解

### 3.1 `reverse(s)` — 字符串反转

**功能**：将输入字符串的字符顺序颠倒后返回新字符串。

**参数**：
- `s` (str)：待反转的字符串

**返回值**：
- `str`：反转后的字符串

**操作步骤**：
1. 导入函数：`from stringkit import reverse`
2. 调用函数并传入字符串

**示例**：

```python
from stringkit import reverse

# 普通字符串
result = reverse("abc")
print(result)  # 输出: cba

# 空字符串
result = reverse("")
print(result)  # 输出: (空字符串)

# 含空格的字符串
result = reverse("hello world")
print(result)  # 输出: dlrow olleh
```

---

### 3.2 `is_palindrome(s)` — 回文判断

**功能**：忽略字符串的大小写和空格后，判断是否为回文字符串。

**参数**：
- `s` (str)：待判断的字符串

**返回值**：
- `bool`：是回文返回 `True`，否则返回 `False`

**处理规则**：
1. 将字符串转为小写
2. 移除所有空格
3. 比较处理后字符串与其反转是否相等

**操作步骤**：
1. 导入函数：`from stringkit import is_palindrome`
2. 调用函数并传入字符串

**示例**：

```python
from stringkit import is_palindrome

# 经典回文句（忽略大小写和空格）
result = is_palindrome("A man a plan a canal Panama")
print(result)  # 输出: True

# 普通回文
result = is_palindrome("Madam")
print(result)  # 输出: True

# 非回文
result = is_palindrome("hello")
print(result)  # 输出: False
```

---

### 3.3 `count_vowels(s)` — 元音统计

**功能**：统计字符串中元音字母（a/e/i/o/u，不区分大小写）的个数。

> **注意**：元音字母仅指 a/e/i/o/u，不包含 y/Y。

**参数**：
- `s` (str)：待统计的字符串

**返回值**：
- `int`：元音字母的总数

**操作步骤**：
1. 导入函数：`from stringkit import count_vowels`
2. 调用函数并传入字符串

**示例**：

```python
from stringkit import count_vowels

# 普通字符串
result = count_vowels("hello")
print(result)  # 输出: 2

# 全大写元音
result = count_vowels("AEIOU")
print(result)  # 输出: 5

# 无元音
result = count_vowels("rhythm")
print(result)  # 输出: 0

# 含非字母字符
result = count_vowels("h3ll0!")
print(result)  # 输出: 0
```

---

## 4. 测试覆盖说明

`stringkit` 包含完整的单元测试套件，共 **21 个测试用例**，覆盖以下场景：

- `reverse`：空串、单字符、普通字符串、含空格字符串
- `is_palindrome`：纯回文、忽略大小写、忽略空格、非回文
- `count_vowels`：空串、无元音、全元音、混合大小写、含非字母字符

**测试结果**：`21 passed in 0.03s`，全部通过。

---

## 5. 常见问题 FAQ

**Q1：函数是否支持非字符串输入（如整数、列表）？**

A：当前版本未对非字符串类型输入做特殊处理，传入非字符串类型可能导致运行时异常。建议传入前确保参数为 `str` 类型。

**Q2：`is_palindrome` 如何处理大小写和空格？**

A：函数会自动将字符串转为小写并移除所有空格，再进行回文判断。例如 `"A man a plan a canal Panama"` 和 `"amanaplanacanalpanama"` 均返回 `True`。

**Q3：元音字母是否包含 y/Y？**

A：不包含。当前版本仅统计 a/e/i/o/u（含大小写），y/Y 不计入元音。

**Q4：函数是否会修改原始字符串？**

A：不会。所有函数均为纯函数，不修改输入参数，仅返回计算结果。

**Q5：如何查看函数的详细说明？**

A：可使用 Python 内置帮助功能：
```python
help(reverse)
help(is_palindrome)
help(count_vowels)
```

---

## 6. 附录：完整代码示例

```python
from stringkit import reverse, is_palindrome, count_vowels

# ========== reverse 示例 ==========
print(reverse("abc"))           # cba
print(reverse(""))              # (空)
print(reverse("hello world"))   # dlrow olleh

# ========== is_palindrome 示例 ==========
print(is_palindrome("A man a plan a canal Panama"))  # True
print(is_palindrome("Madam"))                         # True
print(is_palindrome("hello"))                         # False

# ========== count_vowels 示例 ==========
print(count_vowels("hello"))    # 2
print(count_vowels("AEIOU"))    # 5
print(count_vowels("rhythm"))   # 0
print(count_vowels("h3ll0!"))   # 0
```