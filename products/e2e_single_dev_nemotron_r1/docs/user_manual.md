# stringkit 用户手册

---

## 1. 功能简介

**stringkit** 是一个轻量级 Python 纯函数工具包，提供三个核心字符串处理功能：

| 函数 | 功能描述 | 适用场景 |
|------|----------|----------|
| `reverse(s)` | 返回字符串 `s` 字符顺序完全反转的新字符串 | 文本倒序、回文校验预处理 |
| `is_palindrome(s)` | 忽略大小写与所有空白字符后判断是否为回文 | 回文检测、文本游戏、数据校验 |
| `count_vowels(s)` | 统计字符串中 ASCII 元音字母（a/e/i/o/u，不区分大小写）出现总次数 | 文本分析、语言学统计、教学演示 |

**核心特性**
- ✅ **零依赖**：仅使用 Python 标准库，无第三方运行时依赖
- ✅ **纯函数**：无副作用、无 I/O、无全局状态，线程安全
- ✅ **类型安全**：完整类型注解，通过 `mypy --strict` 检查
- ✅ **高性能**：时间复杂度 O(n)，额外空间 O(1)
- ✅ **充分测试**：17 个单元测试覆盖正常、边界、异常场景，覆盖率 ≥ 90%

**支持环境**：Python 3.9+

---

## 2. 快速上手

### 2.1 安装

```bash
# 从源码可编辑安装（推荐开发环境）
pip install -e .

# 或直接复制 stringkit/ 目录到项目中使用
```

### 2.2 验证安装

```python
>>> from stringkit import reverse, is_palindrome, count_vowels
>>> reverse("hello")
'olleh'
>>> is_palindrome("racecar")
True
>>> count_vowels("hello")
2
```

### 2.3 运行测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 查看覆盖率
python -m pytest --cov=stringkit tests/
```

---

## 3. 核心功能操作指南

### 3.1 `reverse(s)` — 字符串反转

#### 函数签名
```python
def reverse(s: str) -> str:
    """返回字符串 s 字符顺序完全反转的新字符串。

    Args:
        s: 待反转的字符串。

    Returns:
        反转后的字符串。空字符串返回空字符串。
    """
```

#### 操作步骤
1. 导入函数：`from stringkit import reverse`
2. 调用 `reverse(你的字符串)`
3. 获得反转后的新字符串

#### 示例

| 输入 | 输出 | 说明 |
|------|------|------|
| `"hello"` | `"olleh"` | 普通字符串反转 |
| `""` | `""` | 空字符串返回空字符串 |
| `"a"` | `"a"` | 单字符返回自身 |
| `"Python"` | `"nohtyP"` | 包含大小写 |
| `"12345"` | `"54321"` | 数字字符串 |

```python
from stringkit import reverse

# 基础用法
print(reverse("hello"))        # olleh
print(reverse(""))             # (空行)
print(reverse("a"))            # a

# 实际场景：快速检查回文
def is_palindrome_simple(s: str) -> bool:
    return s == reverse(s)

print(is_palindrome_simple("racecar"))  # True
print(is_palindrome_simple("hello"))    # False
```

#### 注意事项
- 函数**不修改**原字符串，返回新字符串
- 支持任意 Unicode 字符（按代码点反转）
- 非字符串输入会抛出 `TypeError`

---

### 3.2 `is_palindrome(s)` — 回文判断

#### 函数签名
```python
def is_palindrome(s: str) -> bool:
    """忽略大小写与所有空白字符后判断是否为回文。

    Args:
        s: 待判断的字符串。

    Returns:
        True 如果处理后为回文，否则 False。空字符串视为回文。
    """
```

#### 处理规则
1. **忽略大小写**：`A` 与 `a` 视为相同
2. **忽略所有空白字符**：空格、制表符（`\t`）、换行符（`\n`）、回车符（`\r`）等，按 `str.isspace()` 定义
3. **保留标点符号**：逗号、句号等**不**被忽略（按需求规格 A-002）

#### 操作步骤
1. 导入函数：`from stringkit import is_palindrome`
2. 调用 `is_palindrome(你的字符串)`
3. 获得 `True`/`False` 结果

#### 示例

| 输入 | 输出 | 说明 |
|------|------|------|
| `"A man a plan a canal Panama"` | `True` | 经典回文，忽略空格和大小写 |
| `"racecar"` | `True` | 单词回文 |
| `"hello"` | `False` | 非回文 |
| `""` | `True` | 空字符串视为回文 |
| `"A\tb\nb\ra"` | `True` | 包含制表、换行、回车 |
| `"Madam, I'm Adam"` | `False` | 标点符号不被忽略，`m` 与 `,` 不匹配 |

```python
from stringkit import is_palindrome

# 经典回文示例
print(is_palindrome("A man a plan a canal Panama"))  # True
print(is_palindrome("racecar"))                       # True
print(is_palindrome("hello"))                         # False
print(is_palindrome(""))                              # True

# 含空白字符
print(is_palindrome("A\tb\nb\ra"))                    # True

# 标点符号不被忽略
print(is_palindrome("Madam, I'm Adam"))               # False
print(is_palindrome("MadamImAdam"))                   # True
```

#### 典型应用场景
```python
# 批量检测文件中的回文行
def find_palindromes_in_file(filepath: str) -> list[str]:
    with open(filepath, encoding="utf-8") as f:
        return [line.strip() for line in f if is_palindrome(line.strip())]

# 用户输入校验
def validate_palindrome_input(user_input: str) -> str:
    if is_palindrome(user_input):
        return "✅ 是回文！"
    return "❌ 不是回文。"
```

---

### 3.3 `count_vowels(s)` — 元音统计

#### 函数签名
```python
def count_vowels(s: str) -> int:
    """统计字符串中 ASCII 元音字母出现总次数（不区分大小写）。

    Args:
        s: 待统计的字符串。

    Returns:
        元音字母总数。仅统计 a/e/i/o/u（大小写均计），不含带变音符号字母。
    """
```

#### 统计规则
- **统计范围**：`a, e, i, o, u` 及其大写 `A, E, I, O, U`
- **不统计**：带变音符号的字母（如 `á, é, í, ó, ú, à, è, ì, ò, ù, ä, ë, ï, ö, ü` 等）
- **大小写不敏感**：`A` 与 `a` 均计为 1

#### 操作步骤
1. 导入函数：`from stringkit import count_vowels`
2. 调用 `count_vowels(你的字符串)`
3. 获得 `int` 类型的统计结果

#### 示例

| 输入 | 输出 | 说明 |
|------|------|------|
| `"hello"` | `2` | `e`, `o` |
| `"PYTHON"` | `0` | 无元音 |
| `"aeiouAEIOU"` | `10` | 5 个小写 + 5 个大写 |
| `""` | `0` | 空字符串 |
| `"Hello World"` | `3` | `e`, `o`, `o` |
| `"café"` | `2` | `a`, `e`（`é` 不统计） |
| `"über"` | `1` | `u`（`ü` 不统计） |

```python
from stringkit import count_vowels

# 基础统计
print(count_vowels("hello"))           # 2
print(count_vowels("PYTHON"))          # 0
print(count_vowels("aeiouAEIOU"))      # 10
print(count_vowels(""))                # 0

# 实际场景：文本元音密度分析
def vowel_density(text: str) -> float:
    if not text:
        return 0.0
    return count_vowels(text) / len(text)

print(vowel_density("hello world"))    # 0.3 (3/10)
print(vowel_density("rhythm"))         # 0.0

# 批量统计多行文本
lines = ["apple", "banana", "cherry"]
total_vowels = sum(count_vowels(line) for line in lines)
print(f"总元音数: {total_vowels}")      # 总元音数: 7
```

---

## 4. 组合使用示例

### 4.1 回文词提取器
```python
from stringkit import reverse, is_palindrome, count_vowels

def analyze_word(word: str) -> dict:
    """综合分析单词特征"""
    return {
        "original": word,
        "reversed": reverse(word),
        "is_palindrome": is_palindrome(word),
        "vowel_count": count_vowels(word),
        "length": len(word)
    }

words = ["level", "python", "radar", "hello", "A man a plan a canal Panama"]
for w in words:
    print(analyze_word(w))
```

**输出示例：**
```
{'original': 'level', 'reversed': 'level', 'is_palindrome': True, 'vowel_count': 2, 'length': 5}
{'original': 'python', 'reversed': 'nohtyp', 'is_palindrome': False, 'vowel_count': 1, 'length': 6}
{'original': 'radar', 'reversed': 'radar', 'is_palindrome': True, 'vowel_count': 2, 'length': 5}
{'original': 'hello', 'reversed': 'olleh', 'is_palindrome': False, 'vowel_count': 2, 'length': 5}
{'original': 'A man a plan a canal Panama', 'reversed': 'amanaP lanac a nalp a nam A', 'is_palindrome': True, 'vowel_count': 10, 'length': 30}
```

### 4.2 文本处理管道
```python
from stringkit import reverse, is_palindrome, count_vowels

def process_text_pipeline(texts: list[str]) -> list[dict]:
    """批量处理文本：反转、回文检测、元音统计"""
    results = []
    for t in texts:
        results.append({
            "text": t,
            "reversed": reverse(t),
            "palindrome": is_palindrome(t),
            "vowels": count_vowels(t)
        })
    return results

# 使用
sample_texts = ["madam", "hello world", "racecar", "Python"]
for r in process_text_pipeline(sample_texts):
    print(f"{r['text']:15} | 反转: {r['reversed']:15} | 回文: {str(r['palindrome']):5} | 元音: {r['vowels']}")
```

---

## 5. 常见问题 FAQ

### Q1: `is_palindrome` 为什么不忽略标点符号？
**A**: 按需求规格（A-002），`is_palindrome` 仅忽略大小写与空白字符（按 `str.isspace()` 定义）。标点符号（逗号、句号、撇号等）被保留参与比较。如需忽略标点，请自行预处理：
```python
import re
def is_palindrome_ignore_punct(s: str) -> bool:
    cleaned = re.sub(r'[\W_]+', '', s)  # 移除非字母数字字符
    return is_palindrome(cleaned)

print(is_palindrome_ignore_punct("Madam, I'm Adam"))  # True
```

### Q2: `count_vowels` 支持中文或带变音符号的元音吗？
**A**: 不支持。按需求规格（A-003），仅统计 ASCII 元音 `a/e/i/o/u`（不区分大小写）。`á, é, ü, ö` 等不计入。如需 Unicode 元音支持，请自行扩展：
```python
import unicodedata
def count_vowels_unicode(s: str) -> int:
    vowels = set("aeiouAEIOU")
    count = 0
    for ch in s:
        # 归一化后检查基础字符
        base = unicodedata.normalize('NFD', ch)[0]
        if base in vowels:
            count += 1
    return count

print(count_vowels_unicode("café"))   # 2 (a, e)
print(count_vowels_unicode("über"))   # 2 (u, e)
```

### Q3: 函数会修改原字符串吗？
**A**: 不会。所有函数均为**纯函数**，无副作用，输入字符串保持不变，返回新的结果对象。

### Q4: 如何在项目中直接使用而不安装包？
**A**: 将 `stringkit/` 目录复制到你的项目中，确保包含 `__init__.py`，即可直接导入：
```python
# 项目结构
my_project/
├── stringkit/
│   └── __init__.py
└── main.py

# main.py
from stringkit import reverse, is_palindrome, count_vowels
```

### Q5: 测试如何运行？覆盖率如何查看？
**A**:
```bash
# 运行测试
python -m pytest tests/ -v

# 查看覆盖率
python -m pytest --cov=stringkit --cov-report=term-missing tests/
```
预期输出：`17 passed`，覆盖率 ≥ 90%。

### Q6: 支持 Python 3.8 吗？
**A**: 当前要求 Python 3.9+（需求规格 Q-003 待确认）。如需 3.8 兼容，请将类型注解从 `str | None` 改为 `Optional[str]` 等。

### Q7: 可以作为 CLI 工具使用吗？
**A**: 当前版本不提供 CLI 入口（需求规格 Q-005 为范围外扩展）。如需命令行使用，可自行封装：
```python
# cli.py
import sys
from stringkit import reverse, is_palindrome, count_vowels

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python cli.py <func> <text>")
        sys.exit(1)
    func, text = sys.argv[1], sys.argv[2]
    if func == "reverse":
        print(reverse(text))
    elif func == "palindrome":
        print(is_palindrome(text))
    elif func == "vowels":
        print(count_vowels(text))
    else:
        print(f"未知功能: {func}")
```

### Q8: 遇到 `TypeError` 怎么办？
**A**: 确保传入参数为 `str` 类型。非字符串输入会抛出 `TypeError`：
```python
reverse(123)        # TypeError
is_palindrome(None) # TypeError
count_vowels([1,2]) # TypeError
```
请在调用前用 `str()` 转换或做类型检查。

---

## 6. 版本与许可

- **版本**：0.1.0（语义化版本）
- **许可证**：MIT License
- **源码**：见项目根目录 `src/stringkit/__init__.py`

---

## 7. 相关链接

- **README.md**：项目根目录，含安装、API 速查、测试命令
- **测试套件**：`tests/test_stringkit.py`（17 个测试用例）
- **包配置**：`pyproject.toml`（PEP 621 标准）

---

*文档生成自 stringkit v0.1.0 交付上下文。如有问题请参考源码或提交 Issue。*