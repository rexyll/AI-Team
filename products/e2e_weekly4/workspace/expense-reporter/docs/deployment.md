

# 《expense_reporter》部署指引

> **版本**：1.0.0（草案阶段）  
> **交付路径**：`workspace/expense-reporter/`  
> **生成时间**：2026-07-09（基于已完成模块自动生成）

---

## 一、环境要求

| 项目 | 要求 |
|------|------|
| 运行时 | Python 3.8+ |
| 依赖 | **仅使用 Python 标准库**，无需安装任何第三方包 |
| 网络 | **不访问网络**，完全离线运行 |
| 操作系统 | Linux / macOS / Windows（跨平台） |

---

## 二、依赖安装步骤

本项目无外部依赖，无需 `pip install`。

请确认 Python 环境可用：

```bash
python --version
# 期望输出：Python 3.8.x 或更高
```

---

## 三、配置说明

### 3.1 限额配置文件（`limits.json`）

`--config` 参数指向一个 JSON 文件，定义各报销类别的月度金额上限。

**文件格式示例**：

```json
{
  "travel": 5000.00,
  "meal": 3000.00,
  "office": 2000.00,
  "other": 1000.00
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `travel` | 数字 | 差旅类别月度限额（元） |
| `meal` | 数字 | 餐饮类别月度限额（元） |
| `office` | 数字 | 办公用品类别月度限额（元） |
| `other` | 数字 | 其他类别月度限额（元） |

**注意**：
- 若省略 `--config` 参数，或在 JSON 中缺少某类别，该类别**不做限额校验**，报表中会注明「未设限」。
- 金额以「元」为单位，支持小数。

### 3.2 输入 CSV 格式

| 必需列 | 格式要求 | 说明 |
|--------|----------|------|
| `date` | `YYYY-MM-DD` | 报销日期 |
| `employee` | 字符串 | 员工姓名 |
| `category` | `travel` / `meal` / `office` / `other` | 报销类别 |
| `amount` | 两位小数字符串 | 金额（如 `123.45`） |
| `currency` | 固定为 `CNY` | 币种 |
| `note` | 非空字符串 | 备注 |

CSV 文件编码：**UTF-8**（带或不带 BOM 均可）。多余列会被忽略。

---

## 四、启动与运行命令

### 4.1 基本用法

```bash
python -m expense_reporter input.csv --config limits.json --report report.md
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

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `input.csv` | 是 | — | 报销记录 CSV 文件路径 |
| `--config` | 否 | — | 限额配置 JSON 文件路径 |
| `--report` | 否 | — | Markdown 汇总报表输出路径 |
| `--json` | 否 | — | JSON 机器可读输出路径 |
| `--max-age-days` | 否 | `365` | 日期校验的最早天数范围 |

### 4.3 退出码说明

| 退出码 | 含义 | 处理建议 |
|--------|------|----------|
| `0` | 正常完成，无任何异常记录 | 无需人工复核 |
| `1` | 完成处理，但存在解析错误、异常、重复或超限记录 | 财务人员进行人工复核 |
| `2` | 输入错误（文件不存在、必需列缺失、参数非法） | 检查输入文件与参数配置 |

---

## 五、验证安装

### 5.1 运行测试套件

```bash
cd workspace/expense-reporter
python -m pytest tests/ -v
```

**当前已验证通过的测试**：

| 模块 | 测试数 | 状态 |
|------|--------|------|
| CSV 解析（REQ-001） | 14 | ✅ 通过 |
| 单条记录校验（REQ-002） | 26 | ✅ 通过 |
| **合计** | **40** | **✅ 通过（0.06s）** |

> ⚠️ **注意**：目前仅完成 CSV 解析与基础校验模块。重复检测、限额校验、报表生成、CLI 集成等模块尚未完成，自动化测试套件不完整。

---

## 六、常见部署问题与解决

### 6.1 问题：模块找不到

**现象**：`ModuleNotFoundError: No module named 'expense_reporter'`

**原因**：未在项目根目录下运行，或未使用 `-m` 参数。

**解决**：
```bash
cd workspace/expense-reporter
python -m expense_reporter input.csv
```

### 6.2 问题：CSV 解析失败

**现象**：批量报错，退出码 2

**原因**：
- CSV 缺少必需列（`date`、`employee`、`category`、`amount`、`currency`、`note`）
- 日期格式非 `YYYY-MM-DD`
- 金额非两位小数格式

**解决**：检查 CSV 文件表头与数据格式，确保编码为 UTF-8。

### 6.3 问题：限额校验不生效

**现象**：报表中某类别显示「未设限」

**原因**：
- 未提供 `--config` 参数
- JSON 文件中缺少该类别键

**解决**：检查 `limits.json` 是否包含所需类别键。

---

## 七、回退方式

若部署后发现问题需回退：

1. **保留备份**：在替换新版本前，备份当前部署目录。
2. **回退步骤**：
   ```bash
   # 1. 恢复旧版本代码
   rm -rf workspace/expense-reporter
   cp -r workspace/expense-reporter.backup workspace/expense-reporter
   
   # 2. 重新运行测试验证
   cd workspace/expense-reporter
   python -m pytest tests/ -v
   ```
3. **数据兼容**：本工具无持久化存储，回退不影响已生成的报表文件。

---

## 八、已知限制

| 编号 | 限制说明 |
|------|----------|
| L-001 | **仅完成基础模块**：CSV 解析（REQ-001）与单条校验（REQ-002）已完成并测试；重复检测、限额校验、报表生成、CLI 集成、性能测试、完整测试套件等模块尚未完成 |
| L-002 | **无图形界面**：工具为纯命令行形式 |
| L-003 | **无数据库**：不存储历史数据，每次独立处理 |
| L-004 | **仅支持 CNY**：币种固定为人民币 |
| L-005 | **重复检测仅限同批次**：不与历史文件比对 |

---

## 九、联系方式

如有疑问，请联系项目交付团队。

---

*本文档基于已完成模块自动生成，后续模块完成后将更新本指引。*