

# stringkit 用户手册

## 1. 功能简介

`stringkit` 是一个 Python 字符串处理工具包，提供以下三个纯函数：

| 函数 | 功能描述 |
|------|----------|
| `reverse(s)` | 将输入字符串反转后返回 |
| `is_palindrome(s)` | 判断输入字符串是否为回文（忽略大小写和空格） |
| `count_vowels(s)` | 统计输入字符串中的元音字母（a/e/i/o/u）个数（不区分大小写） |

**兼容性**：支持 Python 3.6+  
**类型约束**：三个函数均为纯函数，不修改输入参数，不产生副作用。

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

### 2.3 一键体验

```python
from stringkit import reverse, is_palindrome, count_vowels

print(reverse('hello'))
print(is_palindrome('A man a plan a canal Panama'))
print(count_vowels('Hello World'))
```

**预期输出**：

```
olleh
True
3
```

---

## 3. 功能详解与示例

### 3.1 `reverse(s)`

将字符串按字符顺序反转，返回新字符串。

**函数签名**

```python
def reverse(s: str) -> str
```

**使用示例**

| 调用方式 | 输出 |
|----------|------|
| `reverse('abc')` | `'cba'` |
| `reverse('hello world')` | `'dlrow olleh'` |
| `reverse('')` | `''` |
| `reverse('a')` | `'a'` |

**错误处理示例**

```python
reverse(None)   # 抛出 TypeError
reverse(123)    # 抛出 TypeError
```

---

### 3.2 `is_palindrome(s)`

判断字符串是否为回文。比较时忽略大小写和空格，其他字符（标点、数字）保留参与比较。空字符串视为回文。

**函数签名**

```python
def is_palindrome(s: str) -> bool
```

**使用示例**

| 调用方式 | 输出 |
|----------|------|
| `is_palindrome('racecar')` | `True` |
| `is_palindrome('Race Car')` | `True` |
| `is_palindrome('A man a plan a canal Panama')` | `True` |
| `is_palindrome('hello')` | `False` |
| `is_palindrome('')` | `True` |

---

### 3.3 `count_vowels(s)`

统计字符串中元音字母（a/e/i/o/u，不区分大小写）的个数。不含 y/Y。

**函数签名**

```python
def count_vowels(s: str) -> int
```

**使用示例**

| 调用方式 | 输出 |
|----------|------|
| `count_vowels('hello')` | `2` |
| `count_vowels('HEART')` | `3` |
| `count_vowels('rhythm')` | `0` |
| `count_vowels('aeiouAEIOU')` | `10` |
| `count_vowels('')` | `0` |

---

## 4. 常见问题 FAQ

### Q1：如何确认是否安装成功？

运行以下命令验证：

```bash
python -c "from stringkit import reverse, is_palindrome, count_vowels; print('stringkit imported successfully')"
```

若输出 `stringkit imported successfully`，则安装成功。

### Q2：`reverse` 对空字符串返回什么？

返回空字符串 `''`。

### Q3：`is_palindrome` 如何处理大小写和空格？

比较时会自动忽略大小写和空格。例如 `'Race Car'` 与 `'racecar'` 被视为相同。

### Q4：`is_palindrome` 是否也忽略标点符号？

不忽略。仅忽略大小写和空格，标点符号参与比较。例如 `'A man, a plan...'` 中的逗号不会被忽略。

### Q5：`count_vowels` 是否统计字母 y？

不统计。元音仅指 a/e/i/o/u，不区分大小写。

### Q6：传入非字符串（如整数、None）会发生什么？

`reverse` 会抛出 `TypeError`，不会崩溃程序。建议在调用前确保传入字符串类型。

### Q7：是否支持 Unicode 字符？

支持。`reverse` 按码点反转 Unicode 字符串；`is_palindrome` 和 `count_vowels` 仅处理英文元音字母 a/e/i/o/u。

---

## 5. 附录：完整代码示例

```python
from stringkit import reverse, is_palindrome, count_vowels

# reverse 示例
print(reverse("hello"))          # 输出: olleh
print(reverse("hello world"))   # 输出: dlrow olleh

# is_palindrome 示例
print(is_palindrome("racecar"))              # 输出: True
print(is_palindrome("Race Car"))            # 输出: True
print(is_palindrome("A man a plan a canal Panama"))  # 输出: True
print(is_palindrome("hello"))               # 输出: False

# count_vowels 示例
print(count_vowels("hello"))        # 输出: 2
print(count_vowels("HEART"))       # 输出: 3
print(count_vowels("rhythm"))      # 输出: 0
print(count_vowels("aeiouAEIOU"))  # 输出: 10
```

---

*文档版本：1.0 | 适用 stringkit 版本：1.0+*