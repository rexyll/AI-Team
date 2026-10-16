

# stringkit 设计文档

## 1. 项目概述

`stringkit` 是一个 Python 字符串处理工具包，提供三个核心纯函数：字符串反转、回文判断和元音字母统计。项目设计为轻量级纯函数库，无持久化、无网络依赖、无状态，适合在常规业务场景中直接调用。

本设计文档基于 Architect 的架构设计（TASK-001）与 Developer 的实现报告（TASK-002、TASK-003）编写，覆盖已实现的功能及对应的需求编号。

---

## 2. 总体架构

### 2.1 架构分层

```
┌─────────────────────────────────────────────┐
│                 public API                  │
│              __init__.py 导出层              │
├─────────────────────────────────────────────┤
│              core.py  实现层                 │
│        reverse / is_palindrome /            │
│        count_vowels  三个纯函数              │
├─────────────────────────────────────────────┤
│              types.py  类型定义层            │
│           StringInput / CountResult 等       │
├─────────────────────────────────────────────┤
│            tests/  测试隔离层                │
│       test_core.py / test_types.py          │
└─────────────────────────────────────────────┘
```

### 2.2 设计原则

| 原则 | 说明 |
|------|------|
| 单一职责 | 每个函数只完成一项字符串操作，互不耦合 |
| 纯函数 | 无外部依赖，相同输入必得相同输出，无副作用 |
| 显式导出 | 通过 `__init__.py` 明确控制对外公共 API |
| 测试分离 | 测试代码与业务代码物理隔离，便于 CI/CD |

---

## 3. 模块划分与职责

### 3.1 模块总览

| 模块 | 职责 | 依赖 | 实现状态 |
|------|------|------|----------|
| `stringkit/__init__.py` | 包入口，导出公共 API（`reverse`、`is_palindrome`、`count_vowels`） | `core.py`, `types.py` | ✅ 已完成 |
| `stringkit/core.py` | 实现三个核心纯函数，含类型注解与 docstring | `types.py` | ✅ 已完成 |
| `stringkit/types.py` | 统一定义类型别名与常量 | 无 | ✅ 已完成 |
| `stringkit/tests/__init__.py` | 空包标记，使 `tests` 成为可导入包 | 无 | ✅ 已完成 |
| `stringkit/tests/test_core.py` | 对三个核心函数的正常/边界/异常路径测试 | `core.py` | ✅ 已完成 |
| `stringkit/tests/test_types.py` | 类型注解验证、边界值测试 | `types.py` | ✅ 已完成 |
| `tests/test_stringkit.py` | 根目录补充测试文件（17 个用例） | `stringkit.core` | ✅ 已完成 |

### 3.2 需求覆盖映射

| 模块 | 实现的需求编号 |
|------|--------------|
| `stringkit/core.py` | REQ-001、REQ-002、REQ-003 |
| `stringkit/__init__.py` | REQ-001、REQ-002、REQ-003（API 导出） |
| `stringkit/tests/test_core.py` | REQ-004 |
| `stringkit/tests/test_types.py` | REQ-004（类型边界测试） |
| `tests/test_stringkit.py` | REQ-004 |
| `stringkit/` 整体 | REQ-005（配合 README / docstring） |

---

## 4. 关键接口与数据结构

### 4.1 类型定义（`types.py`）

```python
from typing import Union, Tuple, Optional

StringInput   = str
SplitResult   = Tuple[str, ...]
TransformResult = str
FindResult    = Optional[int]
CountResult   = int
BoolResult    = bool
```

### 4.2 核心函数接口

#### `reverse(s: StringInput) -> TransformResult`

- **参数**：`s` (str) — 待反转的源字符串
- **返回**：`str` — 反转后的新字符串
- **对应需求**：REQ-001

**验收用例（部分）**：
| 输入 | 期望输出 | 结果 |
|------|----------|------|
| `"abc"` | `"cba"` | ✅ 通过 |
| `""` | `""` | ✅ 通过 |
| `"a"` | `"a"` | ✅ 通过 |

---

#### `is_palindrome(s: StringInput) -> BoolResult`

- **参数**：`s` (str) — 待判断的字符串
- **返回**：`bool` — 是否为回文（忽略大小写和空格）
- **对应需求**：REQ-002

**验收用例（部分）**：
| 输入 | 期望输出 | 结果 |
|------|----------|------|
| `"Aba"` | `True` | ✅ 通过 |
| `"racecar"` | `True` | ✅ 通过 |
| `"hello"` | `False` | ✅ 通过 |
| `"Never odd or even"` | `True` | ✅ 通过 |

---

#### `count_vowels(s: StringInput) -> CountResult`

- **参数**：`s` (str) — 待统计的字符串
- **返回**：`int` — 元音字母（a, e, i, o, u，大小写均计）出现次数
- **对应需求**：REQ-003

**验收用例（部分）**：
| 输入 | 期望输出 | 结果 |
|------|----------|------|
| `"hello"` | `2` | ✅ 通过 |
| `"bcdfg"` | `0` | ✅ 通过 |
| `"AEIOU"` | `5` | ✅ 通过 |

---

### 4.3 数据结构

项目为纯函数库，无需持久化数据模型。唯一的数据契约为上述函数的参数/返回值类型定义，集中在 `types.py` 中统一管理。

---

## 5. 目录结构

```
stringkit/
├── __init__.py          # 包入口，导出 reverse / is_palindrome / count_vowels
├── core.py              # 三个核心纯函数实现
├── types.py             # 类型别名与常量定义
└── tests/
    ├── __init__.py      # 空包标记
    ├── test_core.py     # 核心函数单元测试
    └── test_types.py    # 类型边界测试

tests/
└── test_stringkit.py    # 根目录补充测试（17 个用例）
```

---

## 6. 关键技术决策及理由

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 包结构 | 标准 Python 包（`stringkit/`） | 符合 PEP 8 与社区惯例，支持 `pip install` 与源码直接使用 |
| 函数设计 | 纯函数，无状态、无副作用 | 满足可测试性要求，相同输入必得相同输出，适合单元测试 |
| 类型注解 | 使用 `typing` 模块定义类型别名 | 提升代码可读性，便于静态类型检查，集中管理在 `types.py` |
| 测试框架 | pytest | 支持 `-v` 详细输出、`--tb=short` 简洁 traceback，生态成熟 |
| 测试与代码分离 | `tests/` 目录独立于源码 | 避免测试代码混入发布包，符合 CI/CD 最佳实践 |
| 元音字母定义 | 仅包含 a, e, i, o, u（不含 y） | 遵从需求假设 A1，不引入歧义 |
| 输入类型约束 | 不做非字符串类型的转换或错误处理 | 遵从需求假设 A3，保持函数签名简洁 |

---

## 7. 测试覆盖总结

| 测试文件 | 用例数 | 结果 | 对应需求 |
|----------|--------|------|----------|
| `stringkit/tests/test_core.py` | 部分 | 通过 | REQ-004 |
| `stringkit/tests/test_types.py` | 部分 | 通过 | REQ-004 |
| `tests/test_stringkit.py` | 17 | 通过 | REQ-004 |
| **合计** | **38 passed** | **全部通过** | REQ-004 |

> 注：测试执行命令为 `pytest stringkit/tests/test_core.py stringkit/tests/test_types.py tests/test_stringkit.py -v`，共 38 个用例全部通过（0.04s）。

---

## 8. 未实现事项

| 需求编号 | 状态 | 说明 |
|----------|------|------|
| REQ-005 | ⚠️ 部分完成 | 函数 docstring 已提供，但独立的用法说明文档（README / doc）尚未生成，需在后续迭代中补充 |

---

*文档版本：v1.0 · 基于 TASK-001～TASK-003 实现报告编写*