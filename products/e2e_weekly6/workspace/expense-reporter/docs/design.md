

# 报销单校验与汇总工具设计文档

## 一、项目概述

| 项目项 | 说明 |
|--------|------|
| 项目名称 | 报销单校验与汇总工具（expense_reporter） |
| 项目背景 | 行政部每月人工核对员工报销 CSV：查金额合法性、查重复报销、对照类别月度限额，再手工汇总成报表，费时且易错 |
| 目标用户 | 行政专员（批量导入报销记录，得到异常清单与汇总报表）；财务复核人员（依据报表与异常清单做人工复核） |
| 交付物位置 | `workspace/expense-reporter/` 目录 |
| 技术约束 | 仅使用 Python 标准库，不引入第三方依赖；金额计算一律使用 `Decimal`，禁止 `float` 聚合；不访问网络；输出信息面向行政人员，中文表述 |
| 范围外 | 图形界面、多币种、Excel 输入、与报销系统集成、数据库持久化 |

本文档描述系统的总体架构、模块划分、关键接口、目录结构、技术决策及实现状态。实现以 **需求规格说明（草案）** 为依据，引用其中的需求编号（如 REQ-001）。

---

## 二、总体架构

系统采用**四层分层架构**，自底向上依次为：数据层、服务层、应用层、基础设施层。各层职责清晰，依赖单向流动。

```
┌─────────────────────────────────────────┐
│           应用层 (reporter)              │
│   - 报告生成、聚合统计、输出格式化       │
├─────────────────────────────────────────┤
│           服务层 (validator)             │
│   - Violation/Duplicate/OverLimit 检测  │
├─────────────────────────────────────────┤
│           数据层 (models + parser)       │
│   - Record 定义、输入解析、ParseError    │
├─────────────────────────────────────────┤
│           基础设施 (config)              │
│   - 规则配置、阈值参数                   │
└─────────────────────────────────────────┘
```

### 分层说明

| 层级 | 职责 | 对应模块 |
|------|------|----------|
| **数据层** | 负责 CSV 文件的读取与解析，将原始文本转换为结构化 `Record` 对象；捕获解析错误并存入 `ParseError` 清单 | `parser` |
| **服务层** | 对有效记录执行三类业务校验：<br>1. 单条记录校验（规则违反）<br>2. 重复报销检测<br>3. 类别月度限额校验 | `validator` |
| **应用层** | 聚合校验结果，生成人类可读的 Markdown 报表和机器可读的 JSON 输出 | `reporter` |
| **基础设施** | 提供限额配置文件的加载、解析与校验；管理命令行参数与退出码契约 | `config`、`main` |

---

## 三、模块划分与职责

### 1. 数据模型模块（`models.py`）

**职责**：定义系统中所有核心数据结构，确保类型安全与一致性。

| 数据模型 | 职责 |
|----------|------|
| `Record` | 表示一条已解析的报销记录，字段包括 `date`、`employee`、`category`、`amount`、`currency`、`note` |
| `ParseError` | 记录解析失败的信息，包含 `line_no`（行号）与 `reason`（原因） |
| `Violation` | 记录单条记录违反校验规则的信息，包含 `line_no`、`rule`（规则名）、`value`（原始字段值） |
| `Duplicate` | 记录重复报销的信息，包含 `line_no`、`key`（重复键） |
| `OverLimit` | 记录超限报销的信息，包含 `line_no`、`category`、`limit`、`excess` |

**实现状态**：模型定义已完成，字段命名与需求规格一致。

**覆盖需求**：REQ-001、REQ-002、REQ-003、REQ-004 的数据结构基础。

---

### 2. 解析模块（`parser.py`）

**职责**：读取 UTF-8 编码（带或不带 BOM）的 CSV 文件，按固定表头顺序解析，并将每行转换为 `Record` 对象。遇到字段缺失、格式错误等异常情况时，生成 `ParseError` 并记录，不中断后续解析。

**关键接口**：
- `parse_csv(text: str) -> tuple[list[Record], list[ParseError]]`
- `parse_csv_file(path: Path) -> tuple[list[Record], list[ParseError]]`

**校验规则**：
1. 表头必须包含必需列：`date`、`employee`、`category`、`amount`、`currency`、`note`
2. 日期格式必须为 `YYYY-MM-DD`
3. `amount` 必须为两位小数字符串，并转换为 `Decimal` 类型
4. `currency` 必须为 `"CNY"`
5. 字段数不符或缺失的行记入 `ParseError`

**实现状态**：模块已实现并通过全部测试（18/18 通过，耗时 0.62s）。

**覆盖需求**：**REQ-001（已实现）**

---

### 3. 校验模块（`validator.py`）

**职责**：对解析后的有效记录执行三类业务校验，生成相应的异常清单。

#### 3.1 单条记录校验（REQ-002）
依次检查以下规则，任何一条不满足即生成 `Violation`：
1. `amount > 0`
2. `date` 不晚于当天，且不早于 `--max-age-days` 参数指定天数之前（默认 365）
3. `category` 属于允许集合 `{travel, meal, office, other}`
4. `note` 非空（去空白后）
5. `currency == "CNY"`

#### 3.2 重复报销检测（REQ-003）
- 重复键：`(employee, category, amount, date)`
- 同一批次内第二次及之后出现的行标记为 `Duplicate`
- 重复检测在校验之后进行，仅针对未被判定为异常的记录

#### 3.3 类别月度限额校验（REQ-004）
- 限额配置来自 JSON 文件，键为类别名，值为每月金额上限（元）
- 按员工 × 类别 × 月份聚合有效记录金额
- 超出上限的记录按时间顺序标记为 `OverLimit`，直至剩余额度用尽
- 未提供 `--config` 或配置中缺少某类别时，该部分不做限额校验，并在报告中注明「未设限」

**关键接口**：
- `check_violations(records: list[Record], max_age_days: int) -> list[Violation]`
- `detect_duplicates(records: list[Record]) -> list[Duplicate]`
- `check_over_limit(records: list[Record], config: dict) -> list[OverLimit]`

**实现状态**：模块尚未实现（TASK-003~005 状态为 blocked）。

**覆盖需求**：REQ-002、REQ-003、REQ-004（计划实现）

---

### 4. 报表生成模块（`reporter.py`）

**职责**：生成两种格式的输出：
- **Markdown 汇总报表**（REQ-005）：包含报表头、三维汇总（按员工、按类别、按月份）、四个明细清单（解析错误、异常、重复、超限）
- **JSON 机器可读输出**（REQ-006）：含 `summary`、`anomalies`、`duplicates`、`over_limit`、`parse_errors` 五个键，金额均为字符串（两位小数）

**关键接口**：
- `generate_markdown_report(parse_errors, violations, duplicates, over_limits, records, config_status) -> str`
- `generate_json_output(...) -> dict`

**实现状态**：模块尚未实现（TASK-006、007 状态为 blocked）。

**覆盖需求**：REQ-005、REQ-006（计划实现）

---

### 5. 命令行接口与配置模块（`main.py`、`config.py`）

**职责**：
- 解析命令行参数（REQ-007）
- 加载并校验限额配置文件（REQ-004 的配置文件）
- 协调各模块执行流程
- 根据结果返回退出码（0、1、2）

**关键接口**：
- `parse_args() -> argparse.Namespace`
- `load_config(path: Path | None) -> dict | None`
- `main()`：主入口函数

**实现状态**：模块尚未实现（TASK-008 状态为 blocked）。

**覆盖需求**：REQ-007、REQ-004（配置文件加载）

---

### 6. 测试模块（`tests/`）

**职责**：提供自动化测试套件，覆盖所有需求场景。

**测试文件**：
- `test_models.py`：数据模型测试
- `test_parser.py`：解析模块测试
- `test_validator.py`：校验模块测试
- `test_reporter.py`：报表生成测试

**实现状态**：
- `test_parser.py` 已实现并通过全部测试（REQ-001 验收）。
- 其余测试文件尚未创建（TASK-009、012 状态为 blocked）。

**覆盖需求**：REQ-009（自动化测试，计划实现）

---

### 7. 使用文档模块（`README.md`）

**职责**：说明输入 CSV 格式、限额配置示例、全部参数与退出码表，并提供可复制运行的完整示例。

**实现状态**：文档尚未编写（TASK-011 状态为 blocked）。

**覆盖需求**：REQ-010

---

## 四、关键接口与数据结构

### 1. 公共数据模型

所有模型均定义于 `models.py`，字段类型严格遵循需求规格。

```python
from decimal import Decimal
from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass
class Record:
    line_no: int
    date: date
    employee: str
    category: str
    amount: Decimal
    currency: str
    note: str

@dataclass
class ParseError:
    line_no: int
    reason: str

@dataclass
class Violation:
    line_no: int
    rule: str
    value: str

@dataclass
class Duplicate:
    line_no: int
    key: tuple

@dataclass
class OverLimit:
    line_no: int
    category: str
    limit: Decimal
    excess: Decimal
```

### 2. 模块接口契约

| 模块 | 输入 | 输出 |
|------|------|------|
| `parser.parse_csv_file(path)` | CSV 文件路径 | `(list[Record], list[ParseError])` |
| `validator.check_violations(records, max_age_days)` | 有效记录列表、最大年龄天数 | `list[Violation]` |
| `validator.detect_duplicates(records)` | 有效记录列表 | `list[Duplicate]` |
| `validator.check_over_limit(records, config)` | 有效记录列表、限额配置字典 | `list[OverLimit]` |
| `reporter.generate_markdown_report(...)` | 各类清单、记录列表、配置状态 | Markdown 字符串 |
| `reporter.generate_json_output(...)` | 同上 | 字典（可序列化） |
| `main.parse_args()` | 命令行参数 | `argparse.Namespace` |
| `config.load_config(path)` | 配置文件路径 | 字典或 None |

---

## 五、目录结构

基于架构设计与实际开发进度，项目目录结构如下：

```
workspace/expense-reporter/
├── README.md                         # 使用文档（REQ-010，待实现）
├── expense_reporter/                 # 主包目录
│   ├── __init__.py                   # 包入口
│   ├── models.py                     # 数据模型定义
│   ├── parser.py                     # CSV 解析模块（REQ-001，已实现）
│   ├── validator.py                  # 校验模块（REQ-002~004，待实现）
│   ├── reporter.py                   # 报表生成模块（REQ-005~006，待实现）
│   ├── main.py                       # 命令行接口（REQ-007，待实现）
│   ├── config.py                     # 配置加载（REQ-004，待实现）
│   ├── exceptions.py                 # 自定义异常类型
│   ├── test_csv_parser.py            # 解析模块测试（已实现）
│   └── test_*.py                     # 其他测试文件（待实现）
├── tests/                            # 测试目录（可选，当前测试与源码同包）
│   └── ...
├── config/                           # 配置文件目录
│   └── schema.yaml                   # 数据模型定义/校验规则（可选）
├── requirements.txt                  # 依赖声明（空，因仅用标准库）
└── workspace/expense-reporter/       # 实际交付位置
```

**说明**：
- 实际开发中，包名为 `expense_reporter`（无连字符），测试文件与源码同包存放（`test_csv_parser.py` 位于 `expense_reporter/` 下），符合 Python 项目常见惯例。
- 架构设计原计划将测试文件集中至 `tests/` 目录，但当前实现已调整；后续模块可沿用同包测试或迁移至独立目录。
- 配置文件目录 `config/` 中预留了 `schema.yaml`，用于数据模型校验规则，但当前未使用。

---

## 六、关键技术决策及理由

| 决策 | 理由 |
|------|------|
| **仅使用 Python 标准库** | 需求明确约束“不引入第三方依赖”，降低部署复杂度与安全风险。 |
| **金额计算使用 `Decimal`** | 避免浮点数精度误差（如 0.1 + 0.2 问题），满足“累计 1000 次 0.01 与 0.1 类数据核对分毫不差”的需求。 |
| **CSV 解析支持 UTF-8 BOM** | 用户可能使用不同编辑器导出 CSV，自动剥离 BOM 提升兼容性。 |
| **坏行解析不中断处理** | 需求要求“缺少必需列或某行字段数不符时，将该行记入解析错误清单，不中断其余行的处理”，保证批量处理鲁棒性。 |
| **重复键采用元组 `(employee, category, amount, date)`** | 四个字段唯一标识一条重复记录，与需求“同一员工、同一类别、同一金额、同一日期”完全对应。 |
| **限额按员工×类别×月份独立计算** | 跨月不累计，符合行政报销管理的常见实践，且便于配置与核对。 |
| **退出码 0/1/2 分离正常、异常与输入错误** | 便于 CI/CD 集成与脚本调用，明确区分“业务异常”与“系统错误”。 |
| **输出清单按原始顺序排列** | 便于用户对照原始 CSV 定位问题行。 |

---

## 七、实现状态与后续计划

### 当前已实现
| 需求编号 | 模块 | 状态 | 测试证据 |
|----------|------|------|----------|
| REQ-001 | `parser` | ✅ 已完成 | 18/18 测试通过，耗时 0.62s |
| 数据模型 | `models` | ✅ 已完成 | 已定义 Record、ParseError 等五个核心模型 |
| 解析测试 | `test_csv_parser` | ✅ 已完成 | 覆盖有效/无效 CSV、字段校验、BOM 处理等场景 |

### 待实现模块
| 需求编号 | 模块 | 预计工作量 | 依赖 |
|----------|------|------------|------|
| REQ-002~004 | `validator` | 中等 | 已完成的数据模型与解析模块 |
| REQ-005~006 | `reporter` | 中等 | `validator` 输出结构 |
| REQ-007 | `main`、`config` | 小型 | 所有模块就绪 |
| REQ-008 | 性能优化 | 需基准测试 | 整体模块 |
| REQ-009 | 自动化测试 | 中等 | 所有模块实现 |
| REQ-010 | `README.md` | 小型 | 功能稳定后 |

### 后续步骤
1. 实现 `validator` 模块，完成 REQ-002、REQ-003、REQ-004。
2. 实现 `reporter` 模块，完成 REQ-005、REQ-006。
3. 实现 `main`、`config` 模块，完成 REQ-007。
4. 执行性能测试（REQ-008），必要时优化重复检测与限额校验算法。
5. 补充全量自动化测试（REQ-009），覆盖边界条件与异常路径。
6. 编写 `README.md` 使用文档（REQ-010），提供可运行示例。
7. 进行最终代码审查与交付验收（TASK-013）。

---

## 八、附录

### 附录 A：需求编号与模块映射表

| 需求编号 | 需求描述 | 实现模块 | 当前状态 |
|----------|----------|----------|----------|
| REQ-001 | CSV 读取与解析 | `parser` | ✅ 已实现 |
| REQ-002 | 单条记录校验规则 | `validator` | ⏳ 待实现 |
| REQ-003 | 重复报销检测 | `validator` | ⏳ 待实现 |
| REQ-004 | 类别月度限额校验 | `validator`、`config` | ⏳ 待实现 |
| REQ-005 | Markdown 汇总报表 | `reporter` | ⏳ 待实现 |
| REQ-006 | JSON 机器可读输出 | `reporter` | ⏳ 待实现 |
| REQ-007 | 命令行接口与退出码 | `main`、`config` | ⏳ 待实现 |
| REQ-008 | 处理性能（10,000行<30秒） | 全局优化 | ⏳ 待实现 |
| REQ-009 | 自动化测试 | `tests/` | ⏳ 待实现 |
| REQ-010 | 使用文档 | `README.md` | ⏳ 待实现 |

### 附录 B：技术约束确认

- 仅使用 Python 标准库，不引入第三方依赖。
- 金额计算一律使用 `decimal.Decimal`，禁止 `float` 聚合。
- 不访问网络，所有操作离线完成。
- 输出信息面向行政人员，使用中文表述。
- 输入 CSV 支持 UTF-8 编码（带或不带 BOM）。

---

**文档版本**：v1.0  
**最后更新**：2023-10-26  
**编写人**：交付文档工程师（基于 Architect 与 Developer 上下文）