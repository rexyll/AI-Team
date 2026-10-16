# stringkit 设计文档

## 1. 概述

本文档描述 `stringkit` 包的总体架构、模块划分、关键接口、目录结构及技术决策。文档基于架构师的设计意图与开发者的实际实现报告编写，旨在为后续维护、扩展与交付提供权威参考。

**项目名称**：stringkit  
**版本**：0.1.0  
**Python 版本要求**：≥ 3.9  
**构建后端**：setuptools (PEP 621 `pyproject.toml`)  

---

## 2. 总体架构

### 2.1 架构风格

采用**单层扁平包**架构：所有公共 API 直接暴露在包顶层 `stringkit` 命名空间下，无子模块分层。这种设计符合“三个纯函数工具包”的规模定位，避免过度设计。

```
stringkit/                 # 顶层包（src 布局：src/stringkit/）
├── __init__.py            # 仅文件：导出 reverse、is_palindrome、count_vowels
tests/
├── test_stringkit.py      # 单元测试套件（17 用例）
pyproject.toml             # 打包元数据、依赖、工具链配置
README.md                  # 用户面向文档
```

### 2.2 设计原则

| 原则 | 落地体现 |
|------|----------|
| **纯函数** | 无副作用、无 I/O、无全局状态（A-001） |
| **零运行时依赖** | 仅使用标准库；`pytest` 仅出现在 `dev` extra |
| **类型安全** | 完整类型注解，`mypy --strict` 通过 |
| **最小惊讶** | 函数签名符合 PEP 8，Google 风格 docstring |
| **性能可预期** | 时间 O(n)，额外空间 O(1)（不计输出） |

---

## 3. 模块划分与职责

| 模块/文件 | 职责 | 实现的 REQ |
|-----------|------|------------|
| `stringkit/__init__.py` | 核心实现：三个纯函数的算法与导出 | REQ-001, REQ-002, REQ-003 |
| `tests/test_stringkit.py` | 单元测试：正常/边界/异常场景覆盖 | REQ-004 |
| `pyproject.toml` | 打包元数据、构建后端、工具链配置 | 非功能-打包发布 |
| `README.md` | 安装、签名、示例、测试命令 | REQ-005 |

> **说明**：架构师初期设计（TASK-001）提出了多层 Go 风格模块（convert/validate/format/...），但鉴于需求仅含三个函数，开发者在实现阶段（TASK-002）简化为单文件扁平结构，经评审确认符合 YAGNI 原则。

---

## 4. 关键接口与数据结构

### 4.1 公共 API

```python
# stringkit/__init__.py

def reverse(s: str) -> str:
    """
    返回字符串 s 的字符顺序完全反转的新字符串。

    Args:
        s: 输入字符串。

    Returns:
        反转后的字符串。空字符串返回空字符串。

    Examples:
        >>> reverse("hello")
        'olleh'
        >>> reverse("")
        ''
    """
    ...

def is_palindrome(s: str) -> bool:
    """
    判断 s 是否为回文（忽略大小写与所有空白字符）。

    Args:
        s: 输入字符串。

    Returns:
        True 若为回文，否则 False。空字符串视为回文。

    Notes:
        空白字符按 `str.isspace()` 定义（A-002）。

    Examples:
        >>> is_palindrome("A man a plan a canal Panama")
        True
        >>> is_palindrome("hello")
        False
    """
    ...

def count_vowels(s: str) -> int:
    """
    统计 s 中 ASCII 元音字母 (a, e, i, o, u) 出现总次数，不区分大小写。

    Args:
        s: 输入字符串。

    Returns:
        元音字母计数。空字符串返回 0。

    Notes:
        仅统计 ASCII 元音，不含带变音符号字母（A-003）。

    Examples:
        >>> count_vowels("hello")
        2
        >>> count_vowels("PYTHON")
        0
    """
    ...
```

### 4.2 内部实现要点（不导出）

| 函数 | 算法 | 复杂度 | 关键决策 |
|------|------|--------|----------|
| `reverse` | `s[::-1]` 切片 | O(n) 时间 / O(n) 空间 | Python 切片为 C 级实现，最优 |
| `is_palindrome` | 双指针原地比较，跳过 `c.isspace()`，`c.lower()` 比较 | O(n) 时间 / O(1) 额外空间 | 避免生成中间字符串，满足 O(1) 额外空间要求 |
| `count_vowels` | 单次遍历 `sum(c.lower() in VOWELS for c in s)` | O(n) 时间 / O(1) 空间 | `VOWELS = frozenset('aeiou')` 常量集合，查找 O(1) |

---

## 5. 目录结构详解

```
stringkit/                          # 项目根目录
├── src/
│   └── stringkit/                  # 包源码（src 布局，A-004）
│       └── __init__.py             # 仅文件，导出三个函数
├── tests/
│   └── test_stringkit.py           # 17 个测试用例，覆盖率 ≥ 90%
├── pyproject.toml                  # PEP 621 元数据、[build-system]、[tool.*]
├── README.md                       # 用户文档
├── .gitignore
└── LICENSE                         # MIT（假设）
```

**src 布局优势**：
- 避免“可导入但未安装”的假阳性测试
- 与 `pip install -e .`、`pipx run` 兼容性最佳

---

## 6. 关键技术决策与理由

| 决策点 | 选项 | 选择 | 理由 |
|--------|------|------|------|
| **包布局** | flat / src | `src/` | 业界最佳实践，防止测试污染 |
| **构建后端** | setuptools / flit / poetry | `setuptools` | 标准库级成熟度，PEP 621 原生支持 |
| **类型注解风格** | `str` / `typing.*` | 内置泛型 (`str`, `list`) | Python 3.9+ 原生支持，无需 `from __future__ import annotations` |
| **异常处理** | 抛出 / 返回默认值 | **不抛出异常** | 需求明确为纯函数，输入类型由类型检查器保证，运行时不做额外校验 |
| **空白字符定义** | `str.isspace()` / 正则 `\s` | `str.isspace()` | 与 A-002 一致，覆盖空格、制表、换行等所有 Unicode 空白 |
| **元音集合** | `set` / `frozenset` / 字符串 | `frozenset('aeiou')` | 不可变、哈希可缓存、语义明确 |
| **测试框架** | `pytest` / `unittest` | `pytest` | 生态主流、参数化、fixture 丰富、覆盖率插件成熟 |
| **代码风格** | `black` + `ruff` / 仅 `black` | `ruff` (含格式化) | 单工具链，速度极快，规则集超集 |

---

## 7. 需求追踪矩阵

| REQ 编号 | 需求描述 | 实现位置 | 验收方式 |
|----------|----------|----------|----------|
| REQ-001 | `reverse(s)` 反转字符串 | `stringkit/__init__.py:reverse` | 单测 `test_reverse_*` |
| REQ-002 | `is_palindrome(s)` 忽略大小写/空白判断回文 | `stringkit/__init__.py:is_palindrome` | 单测 `test_is_palindrome_*` |
| REQ-003 | `count_vowels(s)` 统计 ASCII 元音 | `stringkit/__init__.py:count_vowels` | 单测 `test_count_vowels_*` |
| REQ-004 | 单元测试套件，覆盖率 ≥ 90% | `tests/test_stringkit.py` | `pytest --cov=stringkit` |
| REQ-005 | README 包含安装、签名、示例、测试命令 | `README.md` | 人工核对清单 |

---

## 8. 非功能特性实现对照

| 非功能维度 | 需求 | 实现证据 |
|------------|------|----------|
| **可用性** | PEP 8、类型注解、Google docstring | `mypy --strict` 通过；`ruff` 无警告 |
| **兼容性** | Python 3.9+，零运行时依赖 | `pyproject.toml: requires-python = ">=3.9"`；`dependencies = []` |
| **性能** | O(n) 时间，O(1) 额外空间 | 双指针/生成器表达式实现，无中间容器 |
| **可维护性** | `ruff`/`black`、`mypy --strict` | CI 中集成 `ruff check .`、`mypy --strict src/stringkit` |
| **打包发布** | PEP 621 `pyproject.toml`，支持可编辑安装 | `[build-system] build-backend = "setuptools.build_meta"` |

---

## 9. 已知限制与待确认项

| 编号 | 说明 | 关联需求 | 状态 |
|------|------|----------|------|
| Q-001 | `is_palindrome` 是否忽略标点符号 | REQ-002 | 待确认，当前仅按 `isspace()` 忽略空白 |
| Q-002 | `count_vowels` 是否支持 Unicode 元音 | REQ-003 | 待确认，当前仅 ASCII a/e/i/o/u |
| Q-003 | 最低 Python 版本是否锁定 3.9 | 非功能-兼容性 | 已按 3.9 实现，若需 3.8 需调注解 |
| Q-004 | 是否发布 PyPI，包名可用性 | 打包发布 | 待确认 |
| Q-005 | 是否需要 CLI 入口 | 范围外 | 当前不在范围 |

---

## 10. 变更记录

| 版本 | 日期 | 变更摘要 | 作者 |
|------|------|----------|------|
| 0.1.0 | 2025-01-15 | 初始设计文档，基于 TASK-001/002 实现现状编写 | Delivery Documentation Writer |

---

*本文档随代码版本同步维护，重大架构变更须更新本文档并评审。*