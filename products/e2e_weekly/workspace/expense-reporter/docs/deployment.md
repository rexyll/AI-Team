

# expense_reporter 部署指引

> **状态说明**：截至本文档生成时，项目仅有 `parser`（CSV 解析）与 `validator`（单条记录校验）两个模块实现并通过测试；`dup_detect`、`limit_check`、`report`、`cli`、自动化集成测试及使用文档等模块均处于 **blocked** 状态，尚未可交付。本文档仅描述已验证部分的部署方式，并如实标注当前能力边界。

---

## 一、环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | 任意支持 Python 3.7+ 的平台（Windows / macOS / Linux） |
| Python 版本 | ≥ 3.7（仅使用标准库，无需 pip 安装任何包） |
| 文件编码 | 输入 CSV 须为 UTF-8（支持 BOM） |
| 权限要求 | 仅需对输入文件只读、对输出目录可写 |

**验证命令（确认可运行 Python）**：
```bash
python --version
```

---

## 二、依赖安装步骤

本项目 **无任何第三方依赖**。无需执行 `pip install` 或 `requirements.txt` 安装。

若通过 Git 或压缩包获取源码，只需解压/克隆至工作目录即可：
```bash
cd workspace/expense-reporter
```

---

## 三、项目结构（已实现部分）

```
workspace/expense-reporter/
├── expense_reporter/
│   ├── __init__.py
│   ├── __main__.py          # CLI 入口（骨架，尚未联调）
│   ├── parser.py            # CSV 读取与解析
│   └── validator.py         # 单条记录校验
├── tests/
│   ├── test_parser.py
│   └── test_validator.py
├── design.md
└── README.md                # 待完善（REQ-010 blocked）
```

---

## 四、配置说明

### 4.1 输入 CSV 格式

首行表头，顺序固定，多余列忽略：
```
date,employee,category,amount,currency,note
2024-01-15,张三,travel,320.50,CNY,出差高铁票
```
- `date`：`YYYY-MM-DD`
- `amount`：正数（Decimal）
- `currency`：固定 `CNY`
- `category`：`travel / meal / office / other`
- `note`：去除空白后非空

### 4.2 限额配置 JSON（`--config`）

当前 `limit_check` 模块尚未实现，该参数暂不参与运行时逻辑。格式示例（供后续集成参考）：
```json
{
  "travel": 5000.00,
  "meal": 1000.00,
  "office": 2000.00,
  "other": 500.00
}
```

---

## 五、启动 / 运行命令

### 5.1 单元测试（已验证）

```bash
cd workspace/expense-reporter
python -m pytest tests/test_parser.py -v
python -m pytest tests/test_validator.py -v
python -m pytest tests/ -v
```

> 上述三条命令已在 TASK-002 / TASK-003 中实际执行并 **全部通过**（`9 passed`、`27 passed, 4 subtests passed`）。

### 5.2 命令行入口（`python -m expense_reporter`）

**现状说明**：`__main__.py` 骨架已创建，但 CLI 编排层（TASK-008 blocked）未实现，因此 **当前无法通过 `python -m expense_reporter` 完成端到端处理**。

后续当 CLI 模块上线后，预期调用形式为：
```bash
python -m expense_reporter input.csv --config limits.json --report report.md --json report.json --max-age-days 365
```
- `--config`、`--json`、`--max-age-days` 均可省略
- 退出码：`0` 正常无异常、`1` 存在异常/重复/超限、`2` 输入错误（文件不存在、必需列缺失、参数非法）

**当前可单独调用的内部函数**（供二次开发参考）：
```python
from expense_reporter.parser import parse_csv
from expense_reporter.validator import validate_rows

parse_result = parse_csv("input.csv")
validation_results = validate_rows(parse_result.rows, window_days=365)
```

---

## 六、常见部署问题与排查

| 问题现象 | 可能原因 | 处理办法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'expense_reporter'` | 工作目录不在 `expense-reporter` 项目根目录 | 确保 `cd workspace/expense-reporter` 后再执行命令 |
| `python -m pytest` 报未找到 | Python 未将 `pytest` 加入 PATH，或虚拟环境未激活 | 激活对应虚拟环境，或改用 `python -m unittest` 运行自带测试 |
| CSV 解析抛出 `必需列缺失` | 表头顺序错误或缺少 `date, employee, category, amount, currency, note` 之一 | 检查 CSV 首行，确保 6 列齐全且顺序一致 |
| 日期校验失败 | 日期格式非 `YYYY-MM-DD` 或超出 365 天窗口 | 调整日期格式；若历史数据超期，使用 `--max-age-days` 扩大窗口（模块就绪后） |
| `python -m expense_reporter` 报错或无输出 | CLI 模块（TASK-008）尚未实现 | 当前阶段请通过单元测试验证 parser / validator 逻辑；待 CLI 上线后再使用命令行 |

---

## 七、回退方式

1. **版本回退**：项目源码管理采用 Git，可通过 `git checkout <commit>` 回退至上一可用状态。
2. **配置回退**：限额 JSON 或 CSV 输入损坏时，替换为备份文件即可重新运行。
3. **环境隔离**：建议使用 Python 虚拟环境（`python -m venv venv`）以避免与系统 Python 包冲突。

---

## 八、当前交付范围说明

| 模块 | 状态 | 备注 |
|---|---|---|
| CSV 解析（REQ-001） | ✅ 已完成 | 单元测试 9 passed |
| 单条记录校验（REQ-002） | ✅ 已完成 | 单元测试 27 passed |
| 重复报销检测（REQ-003） | 🔴 blocked | — |
| 类别月度限额校验（REQ-004） | 🔴 blocked | — |
| Markdown 汇总报表（REQ-005） | 🔴 blocked | — |
| JSON 机器可读输出（REQ-006） | 🔴 blocked | — |
| 命令行接口（REQ-007） | 🔴 blocked | 骨架已建，未联调 |
| 自动化集成测试（REQ-009） | 🔴 blocked | — |
| 使用文档（REQ-010） | 🔴 blocked | — |

**建议**：在 `dup_detect`、`limit_check`、`report`、`cli` 等模块完成并集成测试通过后，本部署指引将补充完整的端到端命令、报表输出示例及完整退出码场景说明。