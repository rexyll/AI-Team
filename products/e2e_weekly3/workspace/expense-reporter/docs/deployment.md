

# 《部署指引》

## 一、环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | 任意支持 Python 3.8+ 的操作系统（Linux / macOS / Windows） |
| Python 版本 | Python 3.8 及以上 |
| 依赖 | **无第三方依赖**，仅使用 Python 标准库（`csv`、`decimal`、`datetime`、`argparse`、`json`、`pathlib` 等） |
| 网络 | **无需联网**，所有操作离线运行 |

---

## 二、依赖安装步骤

本项目不引入任何第三方依赖，无需安装 pip 包。

仅需确保目标机器已安装 Python 3.8+：

```bash
python --version
```

预期输出类似：`Python 3.8.x` 或更高版本。

---

## 三、项目结构

交付物位于 `workspace/expense-reporter/` 目录下，当前已完成的模块如下：

```
workspace/expense-reporter/
├── pyproject.toml          # 项目元数据与入口点配置
├── expense_reporter/       # 源代码包
│   ├── __init__.py
│   └── parser.py           # CSV 读取与解析模块（REQ-001）
├── test_parser.py          # 解析模块单元测试（11 项）
└── smoke.py                # 冒烟验证脚本
```

> **注意**：根据当前实现进度，仅 **TASK-001（架构设计）** 与 **TASK-002（CSV 解析模块）** 已完成并通过测试。校验、去重、限额检查、报表生成等模块尚未交付，CLI 全功能接口暂不可用。

---

## 四、配置说明

### 4.1 项目配置（pyproject.toml）

`pyproject.toml` 已配置包名与入口点，当前无需修改即可使用。

### 4.2 输入 CSV 格式（REQ-001）

工具读取的 CSV 文件须满足以下要求：

| 列顺序 | 列名 | 格式要求 |
|--------|------|----------|
| 1 | `date` | `YYYY-MM-DD` |
| 2 | `employee` | 员工姓名（非空） |
| 3 | `category` | `travel` / `meal` / `office` / `other` |
| 4 | `amount` | 两位小数金额字符串，如 `123.45` |
| 5 | `currency` | 固定为 `CNY` |
| 6 | `note` | 非空备注（去除空白后） |

- 编码：UTF-8（支持带或不带 BOM）
- 多余列将被忽略
- 缺少必需列或字段数不符的行将记入解析错误清单，不中断处理

### 4.3 限额配置（JSON，REQ-004，未交付）

> 本功能模块当前处于 **blocked** 状态，暂未实现。以下格式供后续参考。

限额配置文件为 JSON 格式，键为类别名，值为每月金额上限（元）：

```json
{
  "travel": 5000.00,
  "meal": 2000.00,
  "office": 1000.00
}
```

---

## 五、启动与运行命令

### 5.1 运行解析模块单元测试

以下命令已在 TASK-002 中验证通过（11 passed in 0.06s）：

```bash
cd workspace/expense-reporter
python -m pytest test_parser.py -v
```

### 5.2 运行冒烟验证

```bash
python smoke.py
```

预期输出：`import ok` + 解析正确。

### 5.3 运行 CLI（解析模块）

```bash
python -m expense_reporter.main <csv_file>
```

> 示例：
> ```bash
> python -m expense_reporter.main input.csv
> ```

---

## 六、常见部署问题与回退

### 6.1 Python 版本不满足

**现象**：导入错误或语法报错。

**解决**：升级 Python 至 3.8+。

```bash
python3 --version
```

### 6.2 找不到模块

**现象**：`ModuleNotFoundError: No module named 'expense_reporter'`。

**解决**：确认当前工作目录位于 `workspace/expense-reporter/` 下，且 `expense_reporter/` 目录与脚本同级。

### 6.3 CSV 解析失败

**现象**：程序报错或输出解析错误清单。

**排查**：
- 确认 CSV 编码为 UTF-8（带/不带 BOM 均支持）
- 确认必需列名拼写正确（`date`、`employee`、`category`、`amount`、`currency`、`note`）
- 检查坏行详情，按行号修正原始数据

### 6.4 回退方式

由于本项目为无状态命令行工具，不涉及持久化配置或数据库，回退策略如下：

| 场景 | 回退方式 |
|------|----------|
| 版本回退 | 替换 `workspace/expense-reporter/` 目录为历史版本即可 |
| 配置回退 | 重新使用之前的 `pyproject.toml` 与 CSV 输入文件 |
| 环境清理 | 删除项目目录，无残留依赖需要卸载 |

---

## 七、当前交付状态说明

| 需求编号 | 模块 | 状态 |
|----------|------|------|
| REQ-001 | CSV 读取与解析 | ✅ 已完成 |
| REQ-002 | 单条记录校验 | 🔴 blocked |
| REQ-003 | 重复报销检测 | 🔴 blocked |
| REQ-004 | 类别月度限额校验 | 🔴 blocked |
| REQ-005 | Markdown 汇总报表 | 🔴 blocked |
| REQ-006 | JSON 机器可读输出 | 🔴 blocked |
| REQ-007 | 命令行接口集成 | 🔴 blocked |
| REQ-008 | 处理性能 | 🔴 blocked |
| REQ-009 | 自动化测试 | 🔴 blocked |
| REQ-010 | README.md 使用文档 | 🔴 blocked |

当前可交付并运行的功能仅为 **CSV 读取与解析模块**（REQ-001）。完整工具链需在其余模块开发完成后统一部署。