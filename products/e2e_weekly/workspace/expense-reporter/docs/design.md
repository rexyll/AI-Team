

# 设计文档

**项目名称**：expense-reporter  
**文档版本**：1.0  
**状态**：部分实现（核心解析与校验模块已完成）  

---

## 一、总体架构

expense-reporter 采用 **分层架构 + 策略模式**，将系统划分为四层，各层职责清晰、相互解耦：

```
┌─────────────────────────────────────────┐
│              CLI Layer                  │  ← 参数解析与执行入口
├─────────────────────────────────────────┤
│          Orchestration Layer            │  ← 流程编排与结果聚合
├──────────┬──────────┬──────────┬────────┤
│ Parser   │ Validator │ DupDetect │LimitCk│  ← 核心处理层（策略接口）
│ (已完成) │ (已完成)  │ (阻塞)   │ (阻塞) │
├──────────┴──────────┴──────────┴────────┤
│           Data Model Layer              │  ← Record 数据结构
└─────────────────────────────────────────┘
```

### 架构原则

1. **组件通过接口解耦**：解析器、验证器、去重器、限额检查器均通过统一接口抽象，支持策略替换与扩展
2. **顺序可配置**：验证器、去重器、限额检查器的处理顺序可根据业务需求调整
3. **数据模型单一职责**：`Record` 与 `ParseResult`、`ValidationResult` 等数据结构独立定义，不耦合处理逻辑
4. **纯标准库约束**：所有实现仅依赖 Python 标准库，不引入第三方依赖

---

## 二、模块划分与职责

| 模块 | 职责 | 输入 | 输出 | 实现状态 |
|------|------|------|------|----------|
| `cli` | 参数解析、执行编排、退出码控制 | CLI 参数 | 执行结果与退出码 | 阻塞 |
| `orchestrator` | 流程编排：按顺序调用 parser → validator → dup_detect → limit_check → reporter | 原始 CSV 路径、配置参数 | 报告数据（汇总 + 清单） | 阻塞 |
| `parser` | CSV 文件读取与解析，坏行记录到错误清单 | CSV 文件路径 | `ParseResult`（含有效行与解析错误） | ✅ 已完成 |
| `validator` | 单条记录五项校验：金额、日期、类别、备注、币种 | `ExpenseRow`、时间窗口天数 | `ValidationResult`（含异常列表） | ✅ 已完成 |
| `dup_detect` | 同批次内重复记录检测（员工+类别+金额+日期） | 已验证有效记录列表 | 重复记录标记 | 阻塞 |
| `limit_check` | 类别月度限额校验（员工×类别×月份） | 有效记录、限额配置 JSON | 超限记录标记 | 阻塞 |
| `reporter_md` | Markdown 汇总报表生成 | 汇总数据与四个清单 | Markdown 文件 | 阻塞 |
| `reporter_json` | JSON 机器可读输出 | 汇总数据与四个清单 | JSON 文件 | 阻塞 |
| `data_model` | 数据结构定义：`ExpenseRow`、`ParseResult`、`ValidationResult` 等 | — | — | ✅ 已完成 |

---

## 三、关键接口与数据结构

### 3.1 数据模型（Data Model Layer）

```python
@frozen
class ExpenseRow:
    """单笔费用记录"""
    date: date               # 费用发生日期
    employee: str            # 员工姓名
    category: str            # 费用类别（travel/meal/office/other）
    amount: Decimal          # 金额（使用 Decimal 保证精度）
    currency: str            # 币种（默认 CNY）
    note: str                # 备注

class ParseResult:
    """CSV 解析结果"""
    rows: list[ExpenseRow]       # 成功解析的行
    errors: list[ParseError]     # 解析错误清单

class ValidationError:
    """单条校验错误"""
    field: str                   # 字段名
    message: str                 # 错误描述

class ValidationResult:
    """单行校验结果"""
    row: ExpenseRow              # 原始记录
    errors: list[ValidationError] # 命中异常列表
    @property
    def is_valid(self) -> bool   # 是否通过所有校验
```

### 3.2 核心接口（Core Processing Layer）

#### Parser 模块

```python
def parse_csv(path: str) -> ParseResult
"""
解析 CSV 文件：
- 自动处理 UTF-8 BOM
- 校验必需列：date、employee、category、amount、currency、note
- 坏行记入 errors，不中断其余行处理
"""
```

#### Validator 模块

```python
def validate_row(row: ExpenseRow, *, window_days: int = 365) -> ValidationResult
"""
对单条记录执行五项校验：
1. amount > 0
2. date 在允许时间窗口内（--max-age-days）
3. category ∈ {travel, meal, office, other}
4. note 去空白后非空
5. currency == 'CNY'
命中多条规则时逐条收集
"""

def validate_rows(rows: list[ExpenseRow], *, window_days: int = 365) -> list[ValidationResult]
"""批量校验，返回每条记录的 ValidationResult"""
```

#### DupDetect 模块（待实现）

```python
def detect_duplicates(rows: list[ExpenseRow]) -> list[tuple[int, ExpenseRow]]
"""
检测同批次内重复记录：
- 键：(employee, category, amount, date)
- 同一键第二次及之后出现的行标记为重复
- 返回重复行的索引与记录
"""
```

#### LimitCheck 模块（待实现）

```python
def check_limits(
    rows: list[ExpenseRow],
    config: dict[str, Decimal] | None
) -> list[tuple[int, ExpenseRow]]
"""
按「员工 × 类别 × 月份」聚合有效记录金额，超出上限的记录标记为超限。
未提供 --config 或配置中缺少某类别时，该部分不做限额校验。
"""
```

### 3.3 CLI 接口

```
python -m expense_reporter input.csv [OPTIONS]

OPTIONS:
  --config PATH        限额配置文件路径（JSON）
  --report PATH        Markdown 报表输出路径
  --json PATH          JSON 机器可读输出路径
  --max-age-days INT   日期窗口天数（默认 365）
```

### 3.4 退出码契约

| 退出码 | 含义 |
|--------|------|
| `0` | 正常完成且无任何异常（解析错误、异常、重复、超限均为空） |
| `1` | 完成处理但存在解析错误、异常、重复或超限记录 |
| `2` | 输入错误（输入文件不存在、必需列缺失、参数非法） |

---

## 四、目录结构

```
workspace/expense-reporter/
├── README.md                           # 使用文档（REQ-010，待实现）
├── expense_reporter/
│   ├── __init__.py                     # 包初始化
│   ├── parser.py                       # CSV 读取与解析模块（REQ-001）
│   ├── validator.py                    # 单条记录校验模块（REQ-002）
│   ├── dup_detect.py                   # 重复报销检测模块（REQ-003，阻塞）
│   ├── limit_check.py                  # 类别月度限额校验模块（REQ-004，阻塞）
│   ├── reporter_md.py                  # Markdown 报表生成模块（REQ-005，阻塞）
│   ├── reporter_json.py                # JSON 机器可读输出模块（REQ-006，阻塞）
│   ├── cli.py                          # 命令行接口模块（REQ-007，阻塞）
│   └── data_model.py                   # 数据结构定义（共享）
└── tests/
    ├── test_parser.py                  # 解析模块测试（9 passed）
    ├── test_validator.py               # 校验模块测试（18 passed）
    ├── test_dup_detect.py              # 重复检测测试（阻塞）
    ├── test_limit_check.py             # 限额校验测试（阻塞）
    ├── test_reporter.py                # 报表生成测试（阻塞）
    ├── test_cli.py                     # CLI 集成测试（阻塞）
    └── conftest.py                     # 测试公共 fixtures
```

---

## 五、关键技术决策及理由

### 决策 1：采用分层架构 + 策略模式

**理由**：
- 各处理组件通过接口解耦，便于后续扩展新数据源（如 JSON、自定义格式）
- 验证器、去重器、限额检查器顺序可配置，适应不同业务场景
- 单测易于编写，不依赖外部系统

### 决策 2：金额一律使用 `Decimal`

**理由**：
- 浮点数存在精度误差（如 `0.1 + 0.2 != 0.3`），无法满足财务场景精度要求
- 验收标准要求累计 1000 次 0.01 与 0.1 类数据后分毫不差
- `decimal` 模块为 Python 标准库，符合无第三方依赖约束

### 决策 3：CSV 解析容忍坏行，不中断处理

**理由**：
- 实际报销 CSV 可能含格式异常行，批量处理场景下应继续处理有效行
- 坏行统一记入解析错误清单，便于行政专员人工复核
- 符合 REQ-001 要求："把该行记入解析错误清单，不中断其余行处理"

### 决策 4：重复检测与限额校验在同批次内进行

**理由**：
- 需求明确限定范围："检测范围仅限同一次导入批次内部，不与历史文件比对"
- 避免引入数据库持久化，符合项目范围外约束
- 简化实现，提升性能

### 决策 5：限额校验按「员工 × 类别 × 月份」粒度独立计算

**理由**：
- 财务复核需精确到月，跨月不累计符合实际业务逻辑
- 配置灵活性高，可按类别设置不同限额
- 未提供配置时不做限额校验，并在报告中注明「未设限」，避免误报

---

## 六、需求实现映射

| 需求编号 | 需求名称 | 实现模块 | 状态 |
|----------|----------|----------|------|
| REQ-001 | CSV 读取与解析 | `parser.py` | ✅ 已完成 |
| REQ-002 | 单条记录校验规则 | `validator.py` | ✅ 已完成 |
| REQ-003 | 重复报销检测 | `dup_detect.py` | ⏸ 阻塞 |
| REQ-004 | 类别月度限额校验 | `limit_check.py` | ⏸ 阻塞 |
| REQ-005 | Markdown 汇总报表 | `reporter_md.py` | ⏸ 阻塞 |
| REQ-006 | JSON 机器可读输出 | `reporter_json.py` | ⏸ 阻塞 |
| REQ-007 | 命令行接口 | `cli.py` | ⏸ 阻塞 |
| REQ-008 | 处理性能 | 全模块 | ⏸ 阻塞 |
| REQ-009 | 自动化测试 | `tests/` | ⏸ 阻塞 |
| REQ-010 | 使用文档 | `README.md` | ⏸ 阻塞 |

---

## 七、已完成模块测试证据

### 7.1 Parser 模块（REQ-001）

**测试文件**：`tests/test_parser.py`  
**测试结果**：`9 passed in 0.16s`  
**覆盖场景**：
- 正常 CSV 解析
- UTF-8 BOM 兼容
- 缺失必需列校验
- 列数不足的坏行处理
- 混合好坏行场景
- 空文件 / 仅表头

### 7.2 Validator 模块（REQ-002）

**测试文件**：`tests/test_validator.py`  
**测试结果**：`27 passed, 4 subtests passed`（含 18 validator + 9 parser 联合测试）  
**覆盖场景**：
- 金额边界（0、负数、正数）
- 日期边界（当天、过去、未来、超龄）
- 类别合法性（允许集合、非法值）
- 备注为空与含空白字符
- 币种校验（CNY、USD 等）
- 多条规则同时命中时的异常逐条列出

---

## 八、阻塞事项与后续计划

### 当前阻塞任务

以下模块因上游依赖尚未完成而阻塞：

| 任务编号 | 模块 | 阻塞原因 |
|----------|------|----------|
| TASK-004 | `dup_detect.py` | 依赖 parser、validator 完成 |
| TASK-005 | `limit_check.py` | 依赖 parser、validator 完成 |
| TASK-006 | `reporter_md.py` | 依赖 parser、validator、dup_detect、limit_check 完成 |
| TASK-007 | `reporter_json.py` | 依赖 reporter_md 数据结构对齐 |
| TASK-008 | `cli.py` | 依赖 orchestrator 完成 |
| TASK-009 | 自动化测试 | 依赖各模块完成 |
| TASK-010 | README.md | 依赖 CLI 接口确定 |
| TASK-011 | 测试审查 | 依赖自动化测试完成 |
| TASK-012 | 最终审核 | 依赖测试审查完成 |

### 后续建议

1. **优先完成核心处理链**：dup_detect → limit_check → orchestrator
2. **并行开发报表模块**：reporter_md 与 reporter_json 可同步进行
3. **集成测试先行**：在完成 CLI 后立即编写集成测试，验证退出码契约
4. **性能测试**：生成 10,000 行合法记录验证 REQ-008 性能要求

---

**文档签署**  
架构师：____________________  日期：____________________  
技术负责人：__________________  日期：____________________