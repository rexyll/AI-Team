

# 设计文档 — stringkit

## 1. 项目概述

`stringkit` 是一个轻量级 Python 字符串处理工具包，提供三个纯字符串处理函数：`reverse`、`is_palindrome`、`count_vowels`。项目无第三方依赖，支持 Python 3.6 及以上版本。

---

## 2. 总体架构

项目采用**单层扁平包结构**，避免过度分层，适用于功能单一、逻辑简单的工具包场景：

```
stringkit/
├── __init__.py      # 公共入口，导出三个核心函数
├── core.py          # 核心实现模块
└── tests/
    ├── __init__.py
    └── test_stringkit.py   # 单元测试套件

README.md
```

- **`core.py`**：包含所有业务逻辑，三个函数均为纯函数，无副作用。
- **`__init__.py`**：作为包的公共 API 入口，将核心函数重新导出，用户可直接 `from stringkit import reverse, is_palindrome, count_vowels`。
- **`tests/test_stringkit.py`**：基于 `pytest` 框架编写，覆盖全部函数的主干与边界场景。

---

## 3. 模块划分与职责

| 模块 | 职责 | 实现的需求编号 |
|------|------|---------------|
| `stringkit/core.py` | 实现三个核心字符串处理函数 | REQ-001、REQ-002、REQ-003 |
| `stringkit/__init__.py` | 从 `core` 导入并暴露公共 API | REQ-005（通过文档间接支持） |
| `tests/test_stringkit.py` | 为三个函数编写完整单元测试 | REQ-004 |
| `README.md` | 提供用法说明与调用示例 | REQ-005 |

---

## 4. 关键接口

### 4.1 函数签名

```python
def reverse(s: str) -> str
    """接收字符串 s，返回反转后的字符串。传入非字符串类型时抛出 TypeError。"""

def is_palindrome(s: str) -> bool
    """忽略大小写和空格，判断字符串是否为回文。传入非字符串类型时抛出 TypeError。"""

def count_vowels(s: str) -> int
    """统计字符串中元音字母（a/e/i/o/u，不区分大小写）的个数。传入非字符串类型时抛出 TypeError。"""
```

### 4.2 返回值说明

| 函数 | 返回类型 | 说明 |
|------|---------|------|
| `reverse` | `str` | 反转后的字符串，`reverse("") == ""` |
| `is_palindrome` | `bool` | 去除空格并统一转为小写后比较；`is_palindrome("") == True` |
| `count_vowels` | `int` | 仅统计 ASCII 元音字母，`count_vowels("") == 0` |

### 4.3 异常行为

所有函数接受 `str` 类型参数，若传入 `None` 或其他类型，按 Python 常规错误处理规范抛出 `TypeError`。

---

## 5. 数据结构

本项目不涉及复杂数据结构，三个函数均为 `str → (str | bool | int)` 的纯函数映射，无状态、无副作用。

---

## 6. 目录结构详细说明

```
stringkit/
│
├── __init__.py
│   └── 职责：从 core 模块导入三个函数，暴露为包级公共 API。
│       调用方式：from stringkit import reverse, is_palindrome, count_vowels
│
├── core.py
│   └── 职责：实现 reverse()、is_palindrome()、count_vowels() 三个函数。
│
└── tests/
    ├── __init__.py
    │
    └── test_stringkit.py
        └── 职责：单元测试套件，共 42 个用例，分为三个测试类：
            - TestReverse（15 个用例）
            - TestIsPalindrome（18 个用例）
            - TestCountVowels（15 个用例）

README.md
    职责：包简介、安装说明、三个函数的用法示例。
```

---

## 7. 关键技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 包结构 | 单层扁平 | 三个函数逻辑简单，无需拆分子模块；扁平结构便于使用和后期维护。 |
| 测试框架 | `pytest` | 符合需求规格中明确指定的测试框架；支持 `-v` 详细输出与结构化测试类。 |
| 类型注解 | 使用 `typing` 标注函数签名 | 明确接口契约，提升可读性，符合现代 Python 开发规范。 |
| 文档形式 | 函数 docstring + `README.md` | 最小化文档负担，API 信息与使用示例均覆盖到位。 |
| 空字符串处理 | `reverse("")` 返回 `""`；`is_palindrome("")` 返回 `True`；`count_vowels("")` 返回 `0` | 边界情况语义清晰，与 Python 切片行为一致，且在测试中覆盖。 |
| 元音定义范围 | 仅 ASCII `a/e/i/o/u`（不区分大小写） | 遵循需求规格假设，不支持带音标拉丁字母。 |
| 空格处理（回文） | 使用 `str.replace(" ", "")` 去除普通空格后再比较 | 遵循需求规格中"忽略空格"的明确定义，不扩展至制表符、换行符等其他空白字符。 |

---

## 8. 需求覆盖矩阵

| 需求编号 | 名称 | 实现位置 | 测试覆盖 |
|----------|------|---------|---------|
| REQ-001 | `reverse(s)` | `core.py` | `TestReverse`（15 个用例） |
| REQ-002 | `is_palindrome(s)` | `core.py` | `TestIsPalindrome`（18 个用例） |
| REQ-003 | `count_vowels(s)` | `core.py` | `TestCountVowels`（15 个用例） |
| REQ-004 | 单元测试 | `tests/test_stringkit.py` | 42 个用例全部通过 |
| REQ-005 | 用法说明 | `README.md` | — |

---

## 9. 运行与验证

```bash
# 运行测试
python -m pytest tests/test_stringkit.py -v

# 预期结果：42 passed
```

测试结果：42 个用例全部通过，无失败项，无遗留问题。