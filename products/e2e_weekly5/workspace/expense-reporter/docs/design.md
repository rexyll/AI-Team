

# 报销单校验与汇总工具（expense_reporter）设计文档

> 本文档基于项目上下文中的需求规格、架构设计与任务实现状态编写，作为可交付的架构规格说明。

---

## 一、总体架构

### 1.1 架构风格

本项目采用 **分层架构（Layered Architecture）**，数据流严格单向：

```
CLI 层（参数解析 / 入口控制）
    ↓
Parser 层（CSV 读取 / 字段解析）
    ↓
Validator 层（规则校验 / 重复检测 / 限额比对）
    ↓
Reporter 层（Markdown 报表 / JSON 输出）
```

各层通过明确的接口契约通信，禁止跨层调用。

### 1.2 架构目标

| 目标 | 说明 |
|------|------|
| 可测试性 | 每层独立单元测试，无需依赖其他层 |
| 可扩展性 | 新增校验规则或报表格式只需扩展对应模块 |
| 可维护性 | 职责单一，模块边界清晰 |
| 无外部依赖 | 纯 Python 标准库实现 |

---

## 二、目录结构

```
workspace/expense-reporter/
├── README.md                    # 使用文档（REQ-010）
├── pyproject.toml               # 项目配置与依赖声明
└── src/
    └── expense_reporter/        # 源码包
        ├── __init__.py          # 公共接口暴露
        ├── cli.py               # CLI 入口与参数解析（REQ-007）
        ├── parser.py            # CSV 读取与解析（REQ-001）
        ├── validator.py         # 校验、去重、限额（REQ-002、REQ-003、REQ-004）
        ├── reporter.py          # Markdown / JSON 报表（REQ-005、REQ-006）
        └── models.py            # 核心数据结构（所有模块）
└── tests/
    ├── __init__.py
    ├── test_parser.py           # 解析模块测试（REQ-001、REQ-009）
    ├── test_validator.py        # 校验模块测试（REQ-002~REQ-004、REQ-009）
    ├── test_reporter.py         # 报表模块测试（REQ-005、REQ-006、REQ-009）
    └── test_cli.py              # CLI 测试（REQ-007、REQ-009）
```

---

## 三、模块划分与职责

### 3.1 models.py — 核心数据结构

| 模型 | 类型 | 职责 |
|------|------|------|
| `ParseError` | dataclass | 记录 CSV 解析失败行：行号、原始内容、错误原因 |
| `ValidationError` | dataclass | 记录单条记录校验失败：行号、字段名、期望值、实际值 |
| `DuplicateRecord` | dataclass | 记录重复报销标识：键字段、出现次数 |
| `OverLimitRecord` | dataclass | 记录超限标识：员工、类别、月份、阈值、实际值 |
| `ExpenseRecord` | dataclass | 内部标准化记录：date、employee、category、amount（Decimal）、currency、note |

**REQ 覆盖：** 支撑所有模块（REQ-001 ~ REQ-007）

---

### 3.2 parser.py — CSV 读取与解析

**职责：**
- 读取 UTF-8 编码 CSV（兼容带 BOM）
- 验证必需列：`date`、`employee`、`category`、`amount`、`currency`、`note`
- 解析每条记录的字段值，转换为内部数据结构
- 收集解析失败行（坏行），不中断处理

**接口：**

```python
def parse_csv(
    file_path: str,
    max_age_days: int = 365
) -> tuple[list[ExpenseRecord], list[ParseError]]:
    """
    返回：(有效记录列表, 解析错误清单)
    """
```

**REQ 覆盖：**
- **REQ-001**：CSV 读取与解析

---

### 3.3 validator.py — 校验、去重、限额

**职责：**

| 子功能 | 说明 | 规则来源 |
|--------|------|----------|
| 单条记录校验 | 金额 > 0、日期范围、类别集合、note 非空、currency = CNY | REQ-002 |
| 重复检测 | 同员工×类别×金额×日期视为重复，标记后续出现项 | REQ-003 |
| 月度限额 | 按员工×类别×月份聚合，超出限额逐条标记 | REQ-004 |

**接口：**

```python
def validate_records(
    records: list[ExpenseRecord],
    config: dict[str, Decimal] | None = None
) -> tuple[
    list[ExpenseRecord],    # 通过校验的有效记录
    list[ValidationError],  # 异常清单
    list[DuplicateRecord],  # 重复清单
    list[OverLimitRecord],  # 超限清单
    list[str]               # 未设限类别提示
]:
    """
    返回：(有效记录, 异常清单, 重复清单, 超限清单, 未设限说明)
    """
```

**REQ 覆盖：**
- **REQ-002**：单条记录校验规则
- **REQ-003**：重复报销检测
- **REQ-004**：类别月度限额校验

---

### 3.4 reporter.py — 报表生成

**职责：**
- 生成 Markdown 格式人类可读报表（REQ-005）
- 生成 JSON 格式机器可读输出（REQ-006，可选）

**接口：**

```python
def generate_markdown_report(
    input_file: str,
    records: list[ExpenseRecord],
    anomalies: list[ValidationError],
    duplicates: list[DuplicateRecord],
    over_limits: list[OverLimitRecord],
    parse_errors: list[ParseError],
    unlimited_notes: list[str]
) -> str:
    """生成 Markdown 报表字符串"""

def generate_json_output(
    records: list[ExpenseRecord],
    anomalies: list[ValidationError],
    duplicates: list[DuplicateRecord],
    over_limits: list[OverLimitRecord],
    parse_errors: list[ParseError],
    unlimited_notes: list[str]
) -> dict:
    """生成 JSON 可序列化字典，金额字段为两位小数字符串"""
```

**REQ 覆盖：**
- **REQ-005**：Markdown 汇总报表
- **REQ-006**：JSON 机器可读输出

---

### 3.5 cli.py — 命令行入口

**职责：**
- 解析命令行参数（`input.csv`、`--config`、`--report`、`--json`、`--max-age-days`）
- 协调各模块调用顺序
- 控制退出码：0 正常、1 存在异常记录、2 输入错误

**接口：**

```python
def main(args: list[str] | None = None) -> int:
    """
    返回值：
      0 - 正常完成且无任何异常记录
      1 - 完成处理但存在解析错误、异常、重复或超限记录
      2 - 输入错误（文件不存在、必需列缺失、参数非法）
    """
```

**REQ 覆盖：**
- **REQ-007**：命令行接口

---

## 四、数据流图

```
                    ┌─────────────────────┐
                    │       cli.py        │
                    │  (参数解析 / 退出码) │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │     parser.py       │
                    │  (CSV → ExpenseRecord)│
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │    validator.py     │
                    │ (校验 / 去重 / 限额) │
                    └──────────┬──────────┘
                               ↓
              ┌────────────────┼────────────────┐
              ↓                ↓                ↓
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │ validate_ok  │  │ anomalies    │  │ duplicates   │
     │ records      │  │ (异常清单)   │  │ (重复清单)   │
     └──────┬───────┘  └──────────────┘  └──────────────┘
            ↓
   ┌──────────────────────┐
   │     reporter.py      │
   │  (Markdown / JSON)   │
   └──────────────────────┘
```

---

## 五、关键技术决策

### 5.1 金额精度：使用 `decimal.Decimal`

**决策：** 所有金额计算使用 `Decimal`，禁止 `float`。

**理由：**
- 需求明确要求累计 1000 次 `0.01` 与 `0.1` 类数据核对分毫不差
- `float` 存在二进制精度丢失（如 `0.1 + 0.2 != 0.3`）
- `Decimal` 可保证十进制精度，符合财务场景要求

**REQ 覆盖：** REQ-001、REQ-002、REQ-004

---

### 5.2 数据模型：使用 `dataclasses`

**决策：** 核心数据结构采用 Python `dataclasses` 定义。

**理由：**
- 代码简洁，自动生成 `__init__`、`__repr__`、`__eq__` 等方法
- 类型标注完善，配合 `typing` 模块提升可读性
- 无需引入第三方库（符合纯标准库约束）

**REQ 覆盖：** 全模块支撑

---

### 5.3 CSV 解析：兼容 BOM 处理

**决策：** 读取 CSV 时检测并去除 UTF-8 BOM（`\ufeff`）。

**理由：**
- Windows Excel 导出 CSV 常带 BOM
- 需求明确要求"带或不带 BOM"均可正确解析
- 使用 `open(..., encoding='utf-8-sig')` 自动处理

**REQ 覆盖：** REQ-001

---

### 5.4 重复检测策略

**决策：** 同批次内按首次出现顺序保留，后续重复项标记。

**理由：**
- 需求明确"仅限同一次导入批次内部比对"
- 先校验后去重：异常记录不参与重复检测
- 键组合：`employee + category + amount + date`

**REQ 覆盖：** REQ-003

---

### 5.5 限额校验策略

**决策：** 按时间顺序逐条累积，剩余额度耗尽时后续记录标记超限。

**理由：**
- 需求明确"超出上限的记录按时间顺序标记为超限"
- 按月聚合，跨月不累计（假设条件确认）
- 未配置限额的类别跳过校验并在报告中注明"未设限"

**REQ 覆盖：** REQ-004

---

### 5.6 退出码契约

**决策：** 严格遵循三种退出码语义。

| 退出码 | 触发条件 |
|--------|----------|
| 0 | 正常完成，无解析错误、无异常、无重复、无超限 |
| 1 | 完成处理，但存在任意上述异常记录 |
| 2 | 输入错误（文件不存在、必需列缺失、参数非法） |

**理由：** 需求明确要求三种退出码场景各有自动化测试证据。

**REQ 覆盖：** REQ-007

---

## 六、模块与 REQ 映射表

| 模块 | 实现的 REQ 编号 |
|------|-----------------|
| `models.py` | 支撑全部（REQ-001 ~ REQ-007） |
| `parser.py` | REQ-001 |
| `validator.py` | REQ-002、REQ-003、REQ-004 |
| `reporter.py` | REQ-005、REQ-006 |
| `cli.py` | REQ-007 |
| `tests/` | REQ-009 |
| `README.md` | REQ-010 |
| 性能设计 | REQ-008（设计目标：10,000 行 < 30 秒） |

---

## 七、非功能性设计

| 维度 | 设计说明 |
|------|----------|
| 可用性 | 输出信息中文表述，报表格式清晰 |
| 安全性 | 纯离线运行，无网络访问；纯标准库，无第三方依赖注入风险 |
| 性能 | 解析与校验采用单次遍历；限额聚合使用 `defaultdict`；预计 10,000 行在 30 秒内完成 |
| 兼容性 | 仅 Python 3.9+ 标准库；无数据库、GUI、外部系统依赖 |
| 数据精度 | 所有金额输入输出为两位小数字符串；内部聚合使用 `Decimal` |

---

## 八、当前状态说明

根据任务实现记录，当前状态如下：

| 任务 | 状态 | 说明 |
|------|------|------|
| TASK-001 架构设计 | ✅ completed | 本文档即基于此产出 |
| TASK-002 ~ TASK-011 | ⚠️ failed / blocked | 实现任务尚未完成 |
| TASK-012 ~ TASK-013 | 🔒 blocked | 测试审查与最终审核待进行 |

**交付说明：**
- 本设计文档为架构规格说明，定义了完整的模块划分、接口契约与关键技术决策
- 实际代码实现、自动化测试与 README 需按照本文档规范继续开发
- 性能目标（REQ-008）需在实现阶段通过计时测试验证

---

*文档版本：v1.0 | 基于 TASK-001 架构设计产出*