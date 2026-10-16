

# 设计文档 — stringkit

## 1. 项目概述

`stringkit` 是一个纯 Python 字符串处理工具包，提供三个无外部依赖的纯函数，附带单元测试与用法说明文档。

**对应需求**：REQ-001、REQ-002、REQ-003、REQ-004、REQ-005

---

## 2. 总体架构

采用标准 Python 包结构，扁平化单模块设计，无类封装、无状态、无副作用。

```
stringkit/
├── stringkit/
│   ├── __init__.py          # 包入口，导出公共 API
│   ├── stringkit.py         # 三个纯函数核心实现
│   ├── test_stringkit.py    # 单元测试（21 个用例）
│   └── usage.md             # 使用说明文档
└── README.md
```

**设计原则**：
- 最小必要结构，避免过度工程
- 单文件单职责，函数签名即接口契约
- 纯函数式风格，不修改输入参数

---

## 3. 模块划分与职责

| 模块 | 路径 | 职责 | 实现需求 |
|------|------|------|----------|
| 核心实现 | `stringkit/stringkit.py` | 实现 `reverse`、`is_palindrome`、`count_vowels` 三个纯函数 | REQ-001、REQ-002、REQ-003 |
| 包入口 | `stringkit/__init__.py` | 导出公共 API，支持 `from stringkit import ...` | REQ-005 |
| 单元测试 | `stringkit/test_stringkit.py` | 覆盖正常场景与边界情况，使用 pytest | REQ-004 |
| 使用说明 | `stringkit/usage.md` | 说明函数名称、参数与返回值 | REQ-005 |

---

## 4. 关键接口与数据结构

### 4.1 函数签名

```python
def reverse(s: str) -> str:
    """返回字符串的反转。"""

def is_palindrome(s: str) -> bool:
    """判断字符串是否回文（忽略大小写和空格）。"""

def count_vowels(s: str) -> int:
    """统计字符串中元音字母（a/e/i/o/u，不区分大小写）的个数。"""
```

### 4.2 处理规则

| 函数 | 处理逻辑 |
|------|----------|
| `reverse` | 直接返回 `s[::-1]` |
| `is_palindrome` | 转小写 → 移除所有空格 → 比较与原串反转是否相等 |
| `count_vowels` | 遍历字符串，计数属于 `{a, e, i, o, u, A, E, I, O, U}` 的字符 |

> 注：元音字母不包含 y/Y（REQ-002 约束）。

### 4.3 数据模型

本项目为纯函数库，无持久化数据模型。函数签名即为接口契约。

---

## 5. 关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 包结构 | 扁平单模块 | 三个函数逻辑简单，无需分层；减少维护成本 |
| 无第三方依赖 | 仅标准库 | 满足兼容性要求，`pip install` 后可直接导入 |
| 测试框架 | pytest | 生态成熟，用例组织灵活，支持 `-v` 详细输出 |
| 测试范围 | 21 个用例 | 覆盖正常输入、空字符串、纯空格、混合大小写、含非字母字符等边界场景 |
| 导入方式 | `__init__.py` 显式导出 | 用户可直接 `from stringkit import reverse`，符合 Python 包惯例 |

---

## 6. 模块需求映射

| 模块 | 实现的 REQ 编号 |
|------|----------------|
| `stringkit.py` | REQ-001、REQ-002、REQ-003 |
| `test_stringkit.py` | REQ-004 |
| `__init__.py` + `usage.md` | REQ-005 |

---

## 7. 验收状态摘要

- **测试执行**：`python -m pytest stringkit/stringkit/test_stringkit.py -v`
- **结果**：21 passed in 0.03s，全部通过
- **遗留问题**：无