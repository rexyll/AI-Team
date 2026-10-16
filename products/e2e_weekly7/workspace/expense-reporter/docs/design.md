

# 设计文档

**项目名称**：expense-reporter  
**版本**：v1.0  
**日期**：2024-01  

---

## 一、项目概述

`expense-reporter` 是一个纯 Python 标准库实现的命令行工具，用于自动处理员工报销记录 CSV 文件，完成数据校验、去重、类别月度限额比对与汇总报表输出。工具面向行政专员与财务复核人员，交付路径为 `workspace/expense-reporter/`。

---

## 二、总体架构

### 2.1 架构风格

系统采用**管道-过滤器（Pipeline-Filter）**架构模式，数据沿单一方向流动，每个阶段独立处理并输出结构化结果。该设计保证了模块间的松耦合与可独立测试性。

```
CSV 输入
    │
    ▼
┌─────────────┐
│   parser    │  CSV 读取与解析
└──────┬──────┘
       │ Record 列表 + ParseError 清单
       ▼
┌─────────────┐
│  validator  │  单条记录五项规则校验
└──────┬──────┘
       │ 有效 Record 列表 + Anomaly 清单
       ▼
┌─────────────┐
│deduplicator │  重复报销检测
└──────┬──────┘
       │ 唯一 Record 列表 + Duplicate 清单
       ▼
┌─────────────┐
│   limiter   │  类别月度限额校验
└──────┬──────┘
       │ 通过限额 Record 列表 + OverLimit 清单
       ▼
┌─────────────┐
│   reporter  │  Markdown / JSON 报表生成
└─────────────┘
```

### 2.2 关键技术决策

| 决策 | 理由 |
|------|------|
| 纯标准库实现（无第三方依赖） | 满足客户约束 C-01，降低部署复杂度 |
| `decimal.Decimal` 内部聚合金额 | 消除浮点数累加误差，通过 REQ-009 精度专项验收 |
| 解析失败不中断整体流程 | 满足 REQ-001 容错要求，坏行进入 ParseError 清单 |
| 重复检测与超限检测独立成清单 | 遵循 REQ-003、REQ-004 独立语义，退出码为 1 而非 0 |
| 限额配置缺失时跳过该类限额校验 | 满足 REQ-004 降级处理要求，报告中注明「未设限」 |

---

## 三、模块划分与职责

### 3.1 模块清单

| 模块 | 文件 | 职责 | 实现状态 |
|------|------|------|----------|
| CLI 入口 | `main.py` | 程序启动入口 | 待实现 |
| 参数解析 | `cli.py` | 解析命令行参数，绑定 `--config`、`--json`、`--report`、`--max-age-days` | 待实现 |
| CSV 解析器 | `parser.py` | 读取 UTF-8（含 BOM）CSV，校验必需列，坏行进入 ParseError 清单 | 待实现 |
| 记录校验器 | `validator.py` | 对每条有效记录执行五项校验规则，命中任一则进入 Anomaly 清单 | 待实现 |
| 重复检测器 | `deduplicator.py` | 基于（employee, category, amount, date）四元组识别重复记录，首次出现保留 | 待实现 |
| 限额校验器 | `limiter.py` | 按员工×类别×月份聚合，超出限额的后续记录标记为 OverLimit | 待实现 |
| 报表生成器 | `reporter.py` | 生成 Markdown 报表与可选 JSON 输出，金额以两位小数字符串表示 | 待实现 |
| 精度工具 | `decimal_utils.py` | 提供金额格式化与 Decimal 运算封装 | 待实现 |
| 数据模型 | `models.py` | 定义 Record、Summary、各异常类型 dataclass | 待实现 |
| 异常定义 | `errors.py` | 定义自定义异常类（ParseError、ValidationException 等） | 待实现 |

### 3.2 模块需求覆盖

| 模块 | 实现的 REQ 编号 |
|------|-----------------|
| `parser.py` | REQ-001 |
| `validator.py` | REQ-002 |
| `deduplicator.py` | REQ-003 |
| `limiter.py` | REQ-004 |
| `reporter.py` | REQ-005、REQ-006 |
| `cli.py`、`main.py` | REQ-007 |
| `tests/` 全量 | REQ-009、REQ-010 |
| 性能验证用例 | REQ-008 |

---

## 四、关键数据结构

### 4.1 Record（费用记录）

```python
@dataclass
class Record:
    date: date
    employee: str
    category: str
    amount: Decimal
    currency: str
    note: str
```

### 4.2 Summary（汇总信息）

```python
@dataclass
class Summary:
    total_records: int
    by_employee: dict      # employee -> {amount, count}
    by_category: dict      # category -> {amount, count}
    by_month: dict         # YYYY-MM -> {amount, count}
```

### 4.3 异常类型

```python
@dataclass
class ParseError:
    line_no: int
    reason: str          # 如"必需列缺失"、"字段数不符"
    raw_fields: list

@dataclass
class Anomaly:
    line_no: int
    violations: list     # 每条违规规则描述
    raw_fields: list

@dataclass
class DuplicateRecord:
    line_no: int
    duplicate_of_line: int

@dataclass
class OverLimitRecord:
    line_no: int
    employee: str
    category: str
    month: str           # YYYY-MM
    exceeded_amount: Decimal
    remaining_limit: Decimal
```

---

## 五、目录结构

```
workspace/expense-reporter/
├── README.md                # 使用文档（REQ-010）
├── expense_reporter/        # 源码包
│   ├── __init__.py
│   ├── main.py              # CLI 入口（REQ-007）
│   ├── cli.py               # 参数解析（REQ-007）
│   ├── parser.py            # CSV 解析（REQ-001）
│   ├── validator.py         # 记录校验（REQ-002）
│   ├── deduplicator.py      # 重复检测（REQ-003）
│   ├── limiter.py           # 限额校验（REQ-004）
│   ├── reporter.py          # 报表生成（REQ-005、REQ-006）
│   ├── decimal_utils.py     # 金额精度工具
│   ├── models.py            # 数据模型
│   └── errors.py            # 异常类型
└── tests/
    ├── conftest.py          # 测试公共 fixture
    ├── test_parser.py       # 解析器测试（REQ-001）
    ├── test_validator.py    # 校验器测试（REQ-002）
    ├── test_deduplicator.py # 重复检测测试（REQ-003）
    ├── test_limiter.py      # 限额校验测试（REQ-004）
    ├── test_reporter.py     # 报表生成测试（REQ-005、REQ-006）
    └── test_integration.py  # 集成测试：退出码、性能（REQ-007、REQ-008、REQ-009）
```

---

## 六、关键接口说明

### 6.1 命令行接口（REQ-007）

```bash
python -m expense_reporter input.csv \
    [--config limits.json] \
    [--report report.md] \
    [--json report.json] \
    [--max-age-days DAYS]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `input.csv` | positional | 是 | — | 输入 CSV 文件路径 |
| `--config` | string | 否 | — | 限额配置 JSON 文件路径 |
| `--report` | string | 否 | `report.md` | Markdown 报表输出路径 |
| `--json` | string | 否 | — | JSON 机器可读输出路径 |
| `--max-age-days` | int | 否 | 365 | 允许报销的最早日期偏移天数 |

**退出码契约**：

| 退出码 | 含义 | 触发条件 |
|--------|------|----------|
| 0 | 正常完成，无任何异常 | 无解析错误、无异常、无重复、无超限 |
| 1 | 完成处理但存在异常记录 | 有解析错误 / 异常 / 重复 / 超限记录之一 |
| 2 | 输入错误 | 输入文件不存在、必需列缺失、参数非法 |

### 6.2 限额配置文件格式（REQ-004）

```json
{
    "travel": 5000.00,
    "meal": 2000.00,
    "office": 1000.00,
    "other": 500.00
}
```

键为类别名，值为该类别每月金额上限（单位：元）。

---

## 七、实现状态说明

| 组件 | 状态 | 备注 |
|------|------|------|
| 架构设计 | ✅ 已完成 | TASK-001 |
| 源码模块（parser/validator/deduplicator/limiter/reporter/cli/models/errors/decimal_utils） | ⏸ 待实现 | TASK-002 ~ TASK-008 blocked |
| 自动化测试 | ⏸ 待实现 | TASK-009 ~ TASK-011 blocked |
| README.md | ⏸ 待实现 | TASK-012 blocked |
| 最终审核与验收 | ⏸ 待进行 | TASK-013 blocked |

> **说明**：本项目架构设计阶段已完成（TASK-001），后续实现任务因阻塞原因尚未启动。本设计文档基于已完成的架构设计产出，后续实现阶段将按模块逐一落实本报告所述的设计内容。

---

## 八、附录：数据流详细说明

```
1. CLI 启动 → 解析参数 → 调用 parser.read_csv(input_path)
2. parser → 返回 (records, parse_errors)
3. validator → 接收 records，返回 (valid_records, anomalies)
4. deduplicator → 接收 valid_records，返回 (unique_records, duplicates)
5. limiter → 接收 unique_records + config，返回 (passed_records, over_limits)
6. reporter → 接收汇总数据与各清单，生成 Markdown / JSON 输出
7. 根据是否有异常记录决定退出码：0（无）或 1（有）
```

---

*文档版本：v1.0 | 基于 TASK-001 架构设计产出*