

# 设计文档 — expense-reporter

## 一、文档信息

| 项目 | 内容 |
|------|------|
| 项目名称 | 报销单校验与汇总工具（expense-reporter） |
| 交付位置 | `workspace/expense-reporter/` |
| 文档版本 | V1.0 |
| 依据 | 需求规格草案（REQ-001~REQ-010）、架构设计报告（TASK-001）、CSV 解析实现报告（TASK-002） |
| 状态说明 | 架构设计与 CSV 解析模块已完成；其余模块处于阻塞状态，本文档同时反映已实现与待实现部分 |

---

## 二、总体架构

### 2.1 架构风格

采用 **管道-过滤器（Pipeline-Filter）** 架构模式，数据沿单向管道流动，每一过滤器对记录施加一项独立变换或检查：

```
CSV 文件
   ↓
[Parser]          → 解析 CSV，分离坏行与好行
   ↓
[Validator]       → 逐条校验 REQ-002 规则
   ↓
[Deduplicator]    → 同批次内重复检测 REQ-003
   ↓
[LimitChecker]    → 类别月度限额校验 REQ-004
   ↓
[ReportGenerator] → 生成 Markdown 报表 REQ-005 / JSON 输出 REQ-006
   ↓
stdout + 文件
```

各过滤器之间通过结构化数据对象传递，不共享全局状态，保证可测试性与可扩展性。

### 2.2 分层设计

```
┌─────────────────────────────────────────┐
│           应用层 (Application)           │
│  · main 入口 / CLI 参数解析 (REQ-007)    │
│  · 限额配置 JSON 加载                    │
│  · 退出码控制                            │
├─────────────────────────────────────────┤
│           处理层 (Processing)            │
│  · Parser      → REQ-001（已实现）       │
│  · Validator   → REQ-002                │
│  · Deduplicator→ REQ-003                │
│  · LimitChecker→ REQ-004                │
├─────────────────────────────────────────┤
│           输出层 (Output)                │
│  · ReportGenerator(Markdown) → REQ-005  │
│  · ReportGenerator(JSON)     → REQ-006  │
├─────────────────────────────────────────┤
│           共享层 (Shared)                │
│  · 公共数据类型 (types/)                │
│  · 工具函数 (utils/)                    │
└─────────────────────────────────────────┘
```

---

## 三、模块划分与职责

### 3.1 模块总览

| 模块 | 文件路径 | 职责 | 对应 REQ | 实现状态 |
|------|----------|------|----------|----------|
| Parser | `expense_reporter/parser.py` | 读取 CSV、验证表头、解析字段、分离坏行 | REQ-001 | ✅ 已完成 |
| Validator | `expense_reporter/validator.py` | 校验金额、日期、类别、note、币种 | REQ-002 | 🔴 阻塞 |
| Deduplicator | `expense_reporter/deduplicator.py` | 同批次内按「员工×类别×金额×日期」去重 | REQ-003 | 🔴 阻塞 |
| LimitChecker | `expense_reporter/limit_checker.py` | 按「员工×类别×月份」聚合并比对限额 | REQ-004 | 🔴 阻塞 |
| ReportGenerator | `expense_reporter/report.py` | 生成 Markdown 报表；可选 JSON 输出 | REQ-005、REQ-006 | 🔴 阻塞 |
| CLI / Main | `expense_reporter/main.py` | 参数解析、管道编排、退出码返回 | REQ-007 | 🟡 部分完成 |
| 类型定义 | `expense_reporter/types/` | 公共数据模型 | — | ✅ 已定义 |

### 3.2 各模块详细说明

#### Parser（CSV 读取与解析）

**实现状态**：已完成（TASK-002）

**职责**：
- 读取 UTF-8 编码（含/不含 BOM）的 CSV 文件
- 验证必需列：`date`、`employee`、`category`、`amount`、`currency`、`note`（顺序固定，多余列忽略）
- 字段数不符的行记为 `field count mismatch` 错误，不中断后续处理
- 坏行与好行分离，返回 `(List[CsvRecord], List[ParseError])`

**对应 REQ**：REQ-001

**测试覆盖**（来自 TASK-002）：
- 基础 CSV、UTF-8 BOM、缺少列、字段数不符
- 无效日期、无效金额、不支持的币种
- 好坏行混合、多余列、空文件、仅表头
- 共 11 项单元测试全部通过（`pytest test_parser.py`，0.06s）

---

#### Validator（单条记录校验）

**职责**：
对每条有效解析的记录依次校验以下规则，任何一条不满足即记入异常清单：
1. `amount` > 0
2. `date` 不晚于当天，且不早于 `--max-age-days` 之前（默认 365 天）
3. `category` 属于允许集合 `{travel, meal, office, other}`
4. `note` 非空（去空白后）
5. `currency` 为 CNY

同一条记录命中多条规则时逐条列出，注明行号、违反规则与原始字段值。

**对应 REQ**：REQ-002

**实现状态**：🔴 阻塞

---

#### Deduplicator（重复报销检测）

**职责**：
- 同一员工、同一类别、同一金额、同一日期视为重复
- 同批次内第二次及之后出现的行标记为「重复」，第一次保留为有效
- 重复检测在校验之后进行，仅针对未被判定为异常的记录
- 重复检测范围仅限同一次导入批次内部

**对应 REQ**：REQ-003

**实现状态**：🔴 阻塞

---

#### LimitChecker（类别月度限额校验）

**职责**：
- 限额配置来自 JSON 文件（`--config`），键为类别名，值为每月金额上限
- 按「员工×类别×月份」聚合有效记录金额，超出上限的记录按时间顺序标记为「超限」
- 未提供 `--config` 或配置中缺少某类别时，该部分不做限额校验，报告中注明「未设限」
- 跨月不累计

**对应 REQ**：REQ-004

**实现状态**：🔴 阻塞

---

#### ReportGenerator（汇总报表）

**职责**：
- 生成 Markdown 报表，包含：
  - 报表头：统计口径、生成时间、输入文件名、总行数
  - 三维汇总：按员工、按类别、按月份的有效金额合计与笔数
  - 明细附录：解析错误清单、异常清单、重复清单、超限清单（无清单时显示「无」）
  - 金额一律两位小数
- 当 `--json` 指定路径时，输出机器可读 JSON，五个键（`summary`、`anomalies`、`duplicates`、`over_limit`、`parse_errors`），所有金额以两位小数字符串表示

**对应 REQ**：REQ-005、REQ-006

**实现状态**：🔴 阻塞

---

#### CLI / Main（命令行接口）

**职责**：
- 调用形式：`python -m expense_reporter input.csv --config limits.json --report report.md --json report.json --max-age-days 365`
- `--config`、`--json`、`--max-age-days` 均可省略
- 退出码契约：
  - `0`：正常完成且无任何异常记录
  - `1`：完成处理但存在解析错误、异常、重复或超限记录
  - `2`：输入错误（文件不存在、必需列缺失、参数非法）

**对应 REQ**：REQ-007

**实现状态**：🟡 部分完成（main.py 框架已存在，管道串联尚未完成）

---

## 四、关键数据结构

### 4.1 ExpenseRecord（报销记录）

```python
@dataclass
class ExpenseRecord:
    row_number: int          # CSV 原始行号
    date: date
    employee: str
    category: str
    amount: Decimal          # 两位小数，禁止 float
    currency: str            # 固定为 CNY
    note: str
```

### 4.2 ParseError（解析错误）

```python
@dataclass
class ParseError:
    row_number: int
    reason: str              # 如 "field count mismatch", "missing required column"
    raw_line: str
```

### 4.3 Anomaly（异常记录）

```python
@dataclass
class Anomaly:
    row_number: int
    rule: str                # 如 "amount_not_positive", "date_out_of_range"
    original_value: str      # 原始字段值
```

### 4.4 DuplicateRecord（重复记录）

```python
@dataclass
class DuplicateRecord:
    row_number: int
    key: str                 # "employee|category|amount|date" 哈希
```

### 4.5 OverLimitRecord（超限记录）

```python
@dataclass
class OverLimitRecord:
    row_number: int
    employee: str
    category: str
    month: str               # YYYY-MM
    spent: Decimal
    limit: Decimal
    remaining: Decimal
```

### 4.6 ReportSummary（汇总数据）

```python
@dataclass
class ReportSummary:
    by_employee: Dict[str, AmountCount]   # employee → (total_amount, count)
    by_category: Dict[str, AmountCount]   # category → (total_amount, count)
    by_month: Dict[str, AmountCount]      # YYYY-MM → (total_amount, count)
```

---

## 五、关键接口/数据流

### 5.1 Parser 接口

```python
def parse_csv(source: str) -> tuple[List[ExpenseRecord], List[ParseError]]:
    """读取 CSV 并分离坏行与好行。
    
    Args:
        source: CSV 文件路径
    
    Returns:
        (有效记录列表, 解析错误列表)
    """
```

### 5.2 Validator 接口

```python
def validate(
    records: List[ExpenseRecord],
    max_age_days: int = 365,
    allowed_categories: Optional[Set[str]] = None,
) -> tuple[List[ExpenseRecord], List[Anomaly]]:
    """逐条校验，返回有效记录与异常清单。"""
```

### 5.3 Deduplicator 接口

```python
def deduplicate(
    records: List[ExpenseRecord],
) -> tuple[List[ExpenseRecord], List[DuplicateRecord]]:
    """同批次内去重，返回保留记录与重复清单。"""
```

### 5.4 LimitChecker 接口

```python
def check_limits(
    records: List[ExpenseRecord],
    config_path: Optional[str],
) -> tuple[List[ExpenseRecord], List[OverLimitRecord], List[str]]:
    """限额校验。未设限的类别返回说明列表。"""
```

### 5.5 ReportGenerator 接口

```python
def generate_markdown(
    summary: ReportSummary,
    parse_errors: List[ParseError],
    anomalies: List[Anomaly],
    duplicates: List[DuplicateRecord],
    over_limit: List[OverLimitRecord],
    input_file: str,
    total_rows: int,
) -> str:
    """生成 Markdown 报表字符串。"""

def generate_json(
    summary: ReportSummary,
    parse_errors: List[ParseError],
    anomalies: List[Anomaly],
    duplicates: List[DuplicateRecord],
    over_limit: List[OverLimitRecord],
) -> dict:
    """生成 JSON 输出字典，所有金额为两位小数字符串。"""
```

### 5.6 管道主流程（main.py）

```python
def run(input_csv: str,
        config_path: Optional[str],
        report_path: str,
        json_path: Optional[str],
        max_age_days: int) -> int:
    # 1. 解析
    records, parse_errors = parse_csv(input_csv)
    # 2. 校验
    records, anomalies = validate(records, max_age_days)
    # 3. 去重
    records, duplicates = deduplicate(records)
    # 4. 限额
    records, over_limit, unlimited_notes = check_limits(records, config_path)
    # 5. 汇总
    summary = build_summary(records)
    # 6. 输出
    markdown = generate_markdown(summary, parse_errors, anomalies,
                                  duplicates, over_limit, input_csv, total_rows)
    write_file(report_path, markdown)
    if json_path:
        json_data = generate_json(summary, parse_errors, anomalies,
                                    duplicates, over_limit)
        write_json(json_path, json_data)
    # 7. 退出码
    return compute_exit_code(parse_errors, anomalies, duplicates, over_limit)
```

---

## 六、目录结构

```
workspace/expense-reporter/
├── pyproject.toml                  # 项目元数据、包名、脚本入口
├── README.md                       # 使用文档（REQ-010，阻塞）
│
├── src/expense_reporter/
│   ├── __init__.py                 # 包导出
│   ├── main.py                     # CLI 入口 / 管道编排（REQ-007，部分完成）
│   │
│   ├── types/                      # 共享数据类型（共享层）
│   │   ├── __init__.py
│   │   ├── record.py               # ExpenseRecord、ParseError 等
│   │   └── error.py                # Anomaly、DuplicateRecord、OverLimitRecord
│   │
│   ├── parser.py                   # CSV 读取与解析（REQ-001 ✅）
│   ├── validator.py                # 单条记录校验（REQ-002 🔴）
│   ├── deduplicator.py             # 重复检测（REQ-003 🔴）
│   ├── limit_checker.py            # 限额校验（REQ-004 🔴）
│   ├── report.py                   # Markdown/JSON 报表（REQ-005、REQ-006 🔴）
│   │
│   └── utils/                      # 工具函数（共享层）
│       ├── __init__.py
│       ├── decimal_utils.py        # Decimal 转换与格式化
│       └── file_utils.py           # 文件读写封装
│
├── tests/                          # 自动化测试（REQ-009 🔴）
│   ├── test_parser.py              # ✅ 11 passed
│   ├── test_validator.py           # 🔴 阻塞
│   ├── test_deduplicator.py        # 🔴 阻塞
│   ├── test_limit_checker.py       # 🔴 阻塞
│   ├── test_report.py              # 🔴 阻塞
│   └── conftest.py                 # 测试 fixtures
│
├── test_parser.py                  # 解析器单独测试（兼容旧路径）
├── smoke.py                        # 冒烟验证脚本
└── data/                           # 样例数据
    ├── sample.csv
    └── limits.json
```

---

## 七、关键技术决策

### 决策 1：金额统一使用 `Decimal` 而非 `float`

**选择**：所有输入输出金额均为 `Decimal`，禁止 `float` 参与聚合计算。

**理由**：
- 浮点数累加存在精度误差（如 `0.1 + 0.2 != 0.3`），验收标准 VS-010 明确要求「累计 1000 次 0.01 与 0.1 类数据累加，结果分毫不差」
- 纯标准库方案下，`decimal.Decimal` 是唯一满足精度要求的内置类型
- 输出时统一格式化为两位小数字符串，保持人类可读性与机器可读性一致

**影响**：扩展点至全项目，`parser.py` 已在实现中遵循此决策。

---

### 决策 2：管道-过滤器架构

**选择**：采用单向管道模式，各过滤器独立、无副作用。

**理由**：
- 每个业务规则（校验、去重、限额）逻辑独立，过滤器模式天然契合
- 便于单模块单元测试（TASK-002 已验证此模式的有效性）
- 避免全局状态污染，支持将来并行化扩展

**影响**：`parser.py` 返回 `(records, errors)` 元组，后续模块按相同模式接受输入、返回输出。

---

### 决策 3：坏行不中断处理

**选择**：解析阶段坏行计入 `ParseError` 清单，好行继续流转，不抛出异常。

**理由**：
- 验收标准 VS-001 要求「坏行全部出现在解析错误清单中且行号正确，好行正常进入后续校验」
- 行政场景下样本 CSV 常含格式不一致的坏行，中断处理会遗漏有效数据

**影响**：`parser.py` 实现中每条坏行记录行号与原因，好行正常解析。

---

### 决策 4：重复检测范围限定在同批次

**选择**：重复检测仅在当次导入的 CSV 内部进行，不跨文件、不持久化。

**理由**：
- 需求规格明确指出「重复检测范围仅限同一次导入批次内部，不与历史文件比对」（ASS-004 隐含）
- 纯标准库离线工具，无数据库支持持久化历史数据
- 降低复杂度，符合「简洁优先」原则

**影响**：`deduplicator.py` 使用内存 `frozenset` 作为去重键索引。

---

### 决策 5：未设限类别标注「未设限」而非报错

**选择**：`--config` 未提供或配置中缺少某类别时，该部分不做限额校验，在报告中注明「未设限」。

**理由**：
- 需求规格明确「未提供 `--config` 或配置中缺少某类别时，该部分不做限额校验」（REQ-004）
- 验收标准 VS-004 要求无配置运行时报告出现「未设限」说明
- 避免工具因配置不完整而拒绝处理有效数据

**影响**：`limit_checker.py` 需维护未设限类别说明列表，传递给 ReportGenerator。

---

## 八、已实现与待实现矩阵

| 模块 | REQ | 实现状态 | 测试状态 | 依据 |
|------|-----|----------|----------|------|
| Parser | REQ-001 | ✅ 完成 | ✅ 11 passed | TASK-002 |
| Validator | REQ-002 | 🔴 阻塞 | — | TASK-003 |
| Deduplicator | REQ-003 | 🔴 阻塞 | — | TASK-004 |
| LimitChecker | REQ-004 | 🔴 阻塞 | — | TASK-005 |
| ReportGenerator (MD) | REQ-005 | 🔴 阻塞 | — | TASK-006 |
| ReportGenerator (JSON) | REQ-006 | 🔴 阻塞 | — | TASK-007 |
| CLI / Main | REQ-007 | 🟡 部分完成 | — | TASK-008 |
| 性能测试 | REQ-008 | — | — | TASK-008 |
| 自动化测试 | REQ-009 | 🔴 阻塞 | — | TASK-009 |
| README 文档 | REQ-010 | 🔴 阻塞 | — | TASK-010 |

---

## 九、验收标准对应关系

| 验收编号 | 对应 REQ | 依赖模块 | 当前状态 |
|----------|----------|----------|----------|
| VS-001 | REQ-001 | Parser | ✅ 可验证 |
| VS-002 | REQ-002 | Validator | 🔴 待实现 |
| VS-003 | REQ-003 | Deduplicator | 🔴 待实现 |
| VS-004 | REQ-004 | LimitChecker | 🔴 待实现 |
| VS-005 | REQ-005 | ReportGenerator | 🔴 待实现 |
| VS-006 | REQ-006 | ReportGenerator(JSON) | 🔴 待实现 |
| VS-007 | REQ-007 | CLI/Main | 🟡 部分 |
| VS-008 | REQ-008 | 全模块 | 🔴 待实现 |
| VS-009 | REQ-009 | 测试套件 | 🔴 待实现 |
| VS-010 | 精度 | 全模块 | 🟡 部分（Parser 已验证） |
| VS-011 | REQ-010 | README | 🔴 待实现 |

---

*本文档基于 ARCHITECT 的架构设计（TASK-001）与 DEVELOPER 的 CSV 解析实现报告（TASK-002）撰写，其余模块的实现状态以 TASK-003 至 TASK-012 的阻塞标记为依据，未编造任何未实现的测试结果。*