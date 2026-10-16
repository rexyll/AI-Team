

# 部署指引 — 报销单校验与汇总工具

> **状态说明**：截至本文档撰写时，项目已完成架构设计（TASK-001），但全部开发任务（TASK-002～TASK-013）均处于 failed/blocked 状态，未有可验证的实现代码、命令或测试证据。本文档仅提供面向运维的配置框架与占位说明，实际部署时需等待核心模块实现完成后补充具体命令与参数。

---

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux / macOS / Windows（Python 标准库，无平台绑定） |
| Python 版本 | Python 3.9+（仅使用标准库） |
| 权限 | 读写 `workspace/expense-reporter/` 目录及 CSV/JSON 输入输出路径即可 |
| 网络 | 离线运行，无需访问任何外部服务 |
| 第三方依赖 | **无**（纯标准库实现） |

### 验证环境

```bash
python --version
# 期望输出：Python 3.9.x 或以上
```

---

## 2. 依赖安装步骤

本项目**不依赖任何第三方包**，无需执行 `pip install`。

若使用 `pyproject.toml` 声明依赖（架构阶段预留），安装命令如下：

```bash
cd workspace/expense-reporter
python -m pip install -e .
```

> 注：当前 `pyproject.toml` 内容为占位，实际依赖列表以实现完成后的文件为准。

---

## 3. 配置说明

### 3.1 限额配置文件（`limits.json`）

JSON 格式，键为类别名，值为每月金额上限（单位：元）：

```json
{
    "travel": 5000.00,
    "meal": 1000.00,
    "office": 2000.00,
    "other": 500.00
}
```

- 未提供 `--config` 或配置中缺少某类别时，该部分**不做限额校验**，并在报告中注明「未设限」。
- 配置路径通过 `--config` 参数传入。

### 3.2 项目目录结构

```
workspace/expense-reporter/
├── README.md
├── pyproject.toml
├── src/
│   └── expense_reporter/
│       ├── __init__.py
│       ├── cli.py
│       ├── parser.py
│       ├── validator.py
│       ├── reporter.py
│       └── models.py
└── tests/
    ├── __init__.py
    ├── test_parser.py
    ├── test_validator.py
    ├── test_reporter.py
    └── test_cli.py
```

> 注：`src/` 与 `tests/` 目录由 TASK-001 架构设计定义，实际文件以开发完成后为准。

---

## 4. 启动 / 运行命令

### 4.1 基本用法

```bash
python -m expense_reporter input.csv --report report.md
```

### 4.2 完整参数

```bash
python -m expense_reporter \
    input.csv \
    --config limits.json \
    --report report.md \
    --json report.json \
    --max-age-days 365
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `input.csv` | ✅ | 报销记录 CSV 文件路径（UTF-8，可带 BOM） |
| `--config` | ❌ | 限额配置文件 JSON 路径 |
| `--report` | ❌ | Markdown 汇总报表输出路径 |
| `--json` | ❌ | JSON 机器可读输出路径 |
| `--max-age-days` | ❌ | 日期检查有效期天数，默认 `365` |

### 4.3 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 正常完成，且无解析错误、异常、重复或超限记录 |
| `1` | 完成处理，但存在解析错误 / 异常 / 重复 / 超限记录之一 |
| `2` | 输入错误（文件不存在、列缺失、参数非法） |

### 4.4 运行测试

```bash
cd workspace/expense-reporter
python -m pytest tests/ -v
```

> 注：自动化测试由 TASK-009/TASK-010 实现，当前尚未完成，测试命令以实际交付为准。

---

## 5. 常见部署问题与回退方式

| 问题现象 | 可能原因 | 排查方式 |
|----------|----------|----------|
| `ModuleNotFoundError: expense_reporter` | 未安装或路径未配置 | 确认在 `workspace/expense-reporter/` 目录下运行；或检查 `PYTHONPATH` |
| 退出码 2，提示必需列缺失 | CSV 表头与 `date,employee,category,amount,currency,node` 不符 | 检查 CSV 第一行，确保字段顺序正确 |
| 超限报告未出现 | 未提供 `--config` 或配置中缺少对应类别 | 检查 `limits.json` 是否包含目标类别 |
| 重复记录未检测 | 批次内记录键字段不一致（员工/类别/金额/日期任一不同） | 核对重复记录的四个关键字段 |
| 金额精度偏差 | 浮点数聚合（应由实现保证使用 `Decimal`） | 联系开发确认；验收时可用累计 1000 次 0.01 数据核对 |

### 5.1 回退方式

- 本工具为**无状态离线命令行程序**，不修改输入文件，不写入数据库，无运行态持久化数据。
- **回退操作**：删除本次生成的 `report.md` / `report.json` 即可恢复至部署前状态。
- 若需重新处理，直接重新执行命令，输入文件保持不变。

---

## 6. 交付物清单

| 文件 | 状态 |
|------|------|
| `workspace/expense-reporter/README.md` | 待实现（TASK-011） |
| `workspace/expense-reporter/src/expense_reporter/` 源码 | 待实现 |
| `workspace/expense-reporter/tests/` 测试套件 | 待实现 |
| `workspace/expense-reporter/pyproject.toml` | 占位（TASK-001） |
| 本《部署指引》 | ✅ 已完成 |

> 本项目整体交付时间取决于 TASK-002～TASK-013 的实现进度。本文档基于 TASK-001 架构设计产出，后续实现完成后需更新命令与测试证据。