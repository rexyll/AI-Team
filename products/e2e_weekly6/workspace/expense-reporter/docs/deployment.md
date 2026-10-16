

# 部署指引

## 1. 概述

本文档描述报销单校验与汇总工具（expense_reporter）的环境要求、安装步骤、配置说明、运行命令及常见问题的处理方法。本工具用于批量校验员工报销 CSV 记录，生成异常清单与汇总报表，供行政专员与财务复核人员使用。

## 2. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10+ / macOS 10.14+ / Linux（主流发行版） |
| Python 版本 | Python 3.8 或更高版本 |
| 依赖 | 仅使用 Python 标准库，无需安装任何第三方包 |
| 磁盘空间 | 约 50 MB（含源码、测试与示例数据） |
| 内存 | ≥ 512 MB 可用内存 |

### 2.1 Python 环境检查

```bash
python --version
```

预期输出示例：`Python 3.10.12`。若版本低于 3.8，请升级 Python。

## 3. 依赖安装

本项目仅依赖 Python 标准库，**无需运行任何 pip 安装命令**。

如需运行自动化测试，需确认 `pytest` 已安装：

```bash
pip install pytest
```

## 4. 项目结构

```
workspace/expense-reporter/
├── README.md                  # 使用文档与示例
├── config/
│   └── schema.yaml            # 数据模型定义/校验规则
├── src/
│   ├── __init__.py            # 包入口
│   ├── models.py              # 公共数据模型
│   ├── parser.py              # CSV 解析模块
│   ├── validator.py           # 校验模块（违规/重复/超限检测）
│   ├── reporter.py            # 报表生成模块
│   └── exceptions.py          # 自定义异常类型
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_parser.py
│   ├── test_validator.py
│   └── test_reporter.py
└── requirements.txt           # 依赖声明（仅含 pytest 用于测试）
```

## 5. 配置说明

### 5.1 限额配置文件（JSON 格式）

限额配置以 JSON 文件形式提供，键为类别名，值为该类别每月金额上限（元）。

示例文件 `limits.json`：

```json
{
    "travel": 5000.00,
    "meal": 1000.00,
    "office": 2000.00,
    "other": 500.00
}
```

**注意**：`--config` 参数可省略。未提供配置时，系统将跳过限额校验，并在报告中注明「未设限」。

### 5.2 输入 CSV 格式

输入文件需为 UTF-8 编码（可带 BOM），包含以下必需列：

| 列名 | 说明 |
|------|------|
| `date` | 报销日期，格式 `YYYY-MM-DD` |
| `employee` | 员工姓名 |
| `category` | 报销类别（travel/meal/office/other） |
| `amount` | 金额（两位小数） |
| `currency` | 币种（仅允许 CNY） |
| `note` | 备注说明（非空） |

表头顺序固定，多余列将被忽略。

## 6. 启动与运行

### 6.1 基本用法

```bash
python -m expense_reporter input.csv --config limits.json --report report.md
```

### 6.2 完整参数说明

```bash
python -m expense_reporter <input_csv> [选项]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `<input_csv>` | 输入 CSV 文件路径（必需） | — |
| `--config` | 限额配置文件路径（JSON） | 无（跳过限额校验） |
| `--report` | Markdown 报表输出路径 | — |
| `--json` | JSON 机器可读输出路径 | — |
| `--max-age-days` | 报销日期有效范围（天数） | 365 |

### 6.3 运行示例

```bash
# 基础运行：仅生成 Markdown 报表
python -m expense_reporter expenses.csv --report report.md

# 完整运行：含限额校验与 JSON 输出
python -m expense_reporter expenses.csv \
    --config limits.json \
    --report report.md \
    --json report.json \
    --max-age-days 365
```

### 6.4 退出码说明

| 退出码 | 含义 |
|--------|------|
| 0 | 正常完成且无任何异常记录 |
| 1 | 完成处理，但存在解析错误、异常、重复或超限记录 |
| 2 | 输入错误（文件不存在、必需列缺失、参数非法） |

## 7. 常见部署问题

### 7.1 导入模块时出现 `ModuleNotFoundError`

**原因**：未在正确的目录下运行命令。

**解决**：确保在包含 `expense_reporter` 包的目录下执行命令：

```bash
cd workspace/expense-reporter
python -m expense_reporter input.csv --report report.md
```

### 7.2 输出文件为空或报表缺少内容

**原因**：退出码为 2，表示输入文件存在问题。

**解决**：
1. 检查输入文件路径是否正确；
2. 确认 CSV 文件编码为 UTF-8（可带 BOM）；
3. 确认必需列名称拼写正确（`date`, `employee`, `category`, `amount`, `currency`, `note`）。

### 7.3 限额校验不生效

**原因**：未提供 `--config` 参数，或配置文件中缺少对应类别。

**解决**：
- 提供有效的限额配置文件路径；
- 检查配置文件中的类别名与 CSV 中的 `category` 值完全一致；
- 未设限的类别将在报告中注明「未设限」。

### 7.4 金额显示精度异常

**原因**：内部计算未使用 `Decimal` 类型导致浮点误差。

**解决**：本工具已强制使用 `Decimal` 进行金额计算，请勿修改源代码中的数值类型。若发现精度问题，请提交 Bug 报告。

## 8. 测试验证

### 8.1 运行单元测试

```bash
python -m pytest tests/ -v
```

### 8.2 验证 CSV 解析模块

```bash
python -m pytest expense_reporter/test_csv_parser.py -v
```

### 8.3 性能验证

生成 10,000 行合法记录的 CSV 文件，执行以下命令验证处理时间：

```bash
time python -m expense_reporter large_test.csv --config limits.json --report report.md
```

预期耗时小于 30 秒。

## 9. 回退方式

### 9.1 版本回退

本项目使用版本控制系统管理。如需回退到历史版本：

```bash
git checkout <commit-hash>
```

### 9.2 配置回退

若新版限额配置出现问题，可使用备份的旧配置文件替换：

```bash
cp limits.json.bak limits.json
python -m expense_reporter input.csv --config limits.json --report report.md
```

### 9.3 临时禁用限额校验

若限额配置导致大量误报，可临时省略 `--config` 参数，跳过限额校验：

```bash
python -m expense_reporter input.csv --report report.md
```

---

**文档版本**：v1.0  
**更新日期**：2026-07-10  
**适用范围**：expense_reporter v1.0 部署与环境配置