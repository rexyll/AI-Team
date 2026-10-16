

# expense_reporter 设计文档

## 1. 概述

本文档描述 `expense_reporter` 命令行工具的架构设计、模块划分、关键接口与数据结构。该工具用于自动完成报销记录 CSV 的解析、校验、重复检测、限额比对与汇总报表输出，交付物位于 `workspace/expense-reporter/` 目录下。

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Layer (cli/)                        │
│   argparse入口 → 参数解析 → 调用main() → 设置退出码           │
├─────────────────────────────────────────────────────────────┤
│                     Core Pipeline                            │
│                                                             │
│  CSV解析 → 校验 → 重复检测 → 限额检查 → 报表生成              │
│     ↓         ↓         ↓         ↓         ↓               │
│  csv_    validator  duplicate   limit_    reporter/         │
│  parser           detector    checker   json_output         │
├─────────────────────────────────────────────────────────────┤
│                    Data Layer                                │
│   Record模型 + 异常类（ParseError/ValidationError等）        │
└─────────────────────────────────────────────────────────────┘
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **单向数据流** | 解析→校验→检测→限额→输出，各阶段独立，便于测试与维护 |
| **错误收集而非中断** | 校验阶段收集所有问题，最后统一决定退出码 |
| **配置驱动** | 限额规则从 `--config` 加载，支持扩展 |

---

## 3. 模块划分与职责

### 3.1 csv_parser — CSV 读取与解析

**职责**：读取 UTF-8 编码（带或不带 BOM）的 CSV 文件，验证必需列，解析每条记录。

**接口**：
```python
def parse_csv(file_path: str) -> tuple[list[ExpenseRecord], list[ParseError]]
```

**关键行为**：
- 必需列：`date`、`employee`、`category`、`amount`、`currency`、`note`
- 缺少必需列或字段数不符时，记录 `ParseError`（含行号与原因），不中断处理
- 多余列直接忽略

**实现状态**：✅ 已完成（REQ-001）

---

### 3.2 validator — 单条记录校验

**职责**：对解析后的记录逐条校验业务规则，收集 `ValidationError`。

**接口**：
```python
def validate(records: list[ExpenseRecord], max_age_days: int = 365) -> list[ValidationError]
```

**校验规则**（REQ-002）：
| # | 规则 | 违规示例 |
|---|------|----------|
| 1 | `amount > 0` | 0、负数、非数字字符串 |
| 2 | date 不早于 `--max-age-days` 天、不晚于当天 | 未来日期、超期日期 |
| 3 | `category ∈ {travel, meal, office, other}` | 未知类别、空字符串 |
| 4 | `note` 去空白后非空 | 空字符串、纯空白 |
| 5 | `currency == 'CNY'` | USD、空字符串 |

**关键行为**：同一条记录命中多条规则时逐条列出。

**实现状态**：✅ 已完成（REQ-002）

---

### 3.3 duplicate_detector — 重复报销检测

**职责**：对通过校验的记录进行重复检测。

**接口**：
```python
def detect_duplicates(records: list[ExpenseRecord]) -> list[tuple[int, ExpenseRecord]]
```

**重复定义**（REQ-003）：同一员工、同一类别、同一金额、同一日期视为重复；同一批次内第二次及之后出现的行标记为「重复」。

**关键行为**：重复检测在校验之后进行，仅针对未被判定为异常的记录。

**实现状态**：🔴 未实现（blocked）

---

### 3.4 limit_checker — 类别月度限额校验

**职责**：按员工×类别×月份聚合有效记录，超出限额的按时间顺序标记。

**接口**：
```python
def check_limits(records: list[ExpenseRecord], config: dict[str, Decimal]) -> list[tuple[int, ExpenseRecord]]
```

**关键行为**（REQ-004）：
- 未提供 `--config` 或配置中缺少某类别时，该部分不做限额校验，报告中注明「未设限」
- 超限记录仍计入汇总，仅在超限清单中单独列出

**实现状态**：🔴 未实现（blocked）

---

### 3.5 reporter / json_output — 报表生成

**职责**：生成 Markdown 汇总报表与可选 JSON 机器可读输出。

**接口**：
```python
def generate_markdown_report(...) -> str
def generate_json_output(...) -> dict
```

**Markdown 报表内容**（REQ-005）：
1. 报表头：统计口径说明、生成时间、输入文件名、总行数
2. 三个汇总维度：按员工、按类别、按月份的有效金额合计与笔数
3. 明细附录：解析错误清单、异常清单、重复清单、超限清单，均含行号
4. 金额一律为两位小数

**JSON 输出内容**（REQ-006）：
- 键：`summary`、`anomalies`、`duplicates`、`over_limit`、`parse_errors`
- 所有金额以字符串表示（两位小数）

**实现状态**：🔴 未实现（blocked）

---

### 3.6 cli — 命令行接口

**职责**：解析命令行参数，协调各模块执行，设置退出码。

**接口**（REQ-007）：
```
python -m expense_reporter input.csv --config limits.json --report report.md --json report.json --max-age-days 365
```

**退出码契约**：
| 退出码 | 语义 |
|--------|------|
| 0 | 正常完成且无任何异常记录 |
| 1 | 完成处理但存在解析错误、异常、重复或超限记录 |
| 2 | 输入错误（输入文件不存在、必需列缺失、参数非法） |

**关键行为**：`--config`、`--json`、`--max-age-days` 均可省略。

**实现状态**：🔴 未实现（blocked）

---

## 4. 关键数据结构

### 4.1 ExpenseRecord

```python
@dataclass(frozen=True)
class ExpenseRecord:
    row_number: int          # CSV 行号
    date: date
    employee: str
    category: str
    amount: Decimal          # 两位小数金额
    currency: str
    note: str
    status: str = 'valid'    # valid / duplicate / over_limit
```

### 4.2 ParseError

```python
@dataclass
class ParseError:
    row_number: int
    reason: str              # 如 "missing-field: date", "invalid-date"
    raw_line: str
```

### 4.3 ValidationError

```python
@dataclass
class ValidationError:
    row_number: int
    rule: str                # 如 "amount>0", "category-invalid"
    message: str
    field_values: dict       # 原始字段值快照
```

---

## 5. 目录结构

```
workspace/expense-reporter/
├── expense_reporter/
│   ├── __init__.py          # 包初始化
│   ├── models.py            # ExpenseRecord, ParseError, ValidationError 定义
│   ├── csv_parser.py        # REQ-001 实现
│   ├── validator.py         # REQ-002 实现
│   ├── duplicate_detector.py  # REQ-003（待实现）
│   ├── limit_checker.py     # REQ-004（待实现）
│   ├── reporter.py          # REQ-005（待实现）
│   ├── json_output.py       # REQ-006（待实现）
│   └── cli.py               # REQ-007（待实现）
├── tests/
│   ├── __init__.py
│   ├── test_csv_parser.py   # 14 项测试 ✅
│   └── test_validator.py    # 26 项测试 ✅
├── README.md                # REQ-010（待实现）
└── ...
```

---

## 6. 关键技术决策

### 6.1 金额精度：使用 Decimal 而非 float

**决策**：所有金额计算使用 `decimal.Decimal`，禁止 float 聚合。

**理由**：需求明确要求 1000 次 0.01 与 0.1 类数据累加不得出现精度误差（REQ-009 验收标准）。

**影响范围**：`models.py` 中 `amount` 字段类型、所有校验与聚合逻辑。

---

### 6.2 错误处理策略：收集而非中断

**决策**：解析与校验阶段收集所有错误，最后统一决定退出码。

**理由**：用户需要完整的问题清单进行人工复核，单次错误不应阻断其余记录的处理（REQ-001、REQ-002）。

**影响范围**：`csv_parser.py`、`validator.py` 的返回类型为 `tuple[list, list]`。

---

### 6.3 重复检测范围：批次内去重

**决策**：重复检测仅限同一次导入批次内部，不与历史文件比对。

**理由**：客户需求已确认【客户已确认】，工具定位为本批次批量处理。

**影响范围**：`duplicate_detector.py` 的实现逻辑。

---

### 6.4 超限记录的处理：保留计入汇总

**决策**：超限记录仍计入汇总报表的金额合计，仅在超限清单中单独列出。

**理由**：客户需求已确认【客户已确认】，财务复核时需要看到完整的金额流向。

**影响范围**：`limit_checker.py` 与报表生成逻辑。

---

## 7. 需求覆盖映射

| 模块 | 实现的 REQ 编号 | 实现状态 |
|------|-----------------|----------|
| `csv_parser.py` | REQ-001 | ✅ 已完成 |
| `validator.py` | REQ-002 | ✅ 已完成 |
| `duplicate_detector.py` | REQ-003 | 🔴 未实现 |
| `limit_checker.py` | REQ-004 | 🔴 未实现 |
| `reporter.py` | REQ-005 | 🔴 未实现 |
| `json_output.py` | REQ-006 | 🔴 未实现 |
| `cli.py` | REQ-007 | 🔴 未实现 |
| 性能测试 | REQ-008 | 🔴 未实现 |
| 自动化测试 | REQ-009 | ⚠️ 部分完成（csv_parser 14项 + validator 26项） |
| 使用文档 | REQ-010 | 🔴 未实现 |

---

## 8. 未完成任务说明

以下模块因开发受阻尚未实现，将在后续迭代中补全：

- **REQ-003 重复报销检测**：`duplicate_detector.py`
- **REQ-004 类别月度限额校验**：`limit_checker.py`
- **REQ-005 Markdown 汇总报表**：`reporter.py`
- **REQ-006 JSON 机器可读输出**：`json_output.py`
- **REQ-007 命令行接口集成**：`cli.py`
- **REQ-008 性能测试**：基准验证用例
- **REQ-009 完整自动化测试**：需覆盖剩余模块
- **REQ-010 使用文档**：`README.md`

---

*文档版本：v1.0*  
*基于 ARCH-001 架构设计与 TASK-001 至 TASK-003 实现报告*