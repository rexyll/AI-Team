

# 部署指引

## 项目状态说明

⚠️ **重要提示**：根据任务实现报告，本项目当前仅完成架构设计（TASK-001），源代码实现、自动化测试、使用文档等模块尚未开发完成。本文档基于架构设计提供预期的部署结构，实际部署命令需待代码实现完成后补充验证。

## 一、环境要求

### 1.1 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux / macOS / Windows |
| Python 版本 | Python 3.8+（标准库兼容） |
| 内存 | ≥ 256MB |
| 磁盘 | ≥ 50MB（含源码与测试） |

### 1.2 依赖说明

本项目**仅使用 Python 标准库**，无第三方依赖：
- `csv` - CSV 文件解析
- `decimal` - 金额精度计算
- `json` - JSON 输出
- `argparse` - 命令行参数解析
- `datetime` - 日期处理
- `dataclasses` - 数据模型定义

## 二、项目结构

```
workspace/expense-reporter/
├── README.md                      # 使用文档（待开发）
├── expense_reporter/              # 源码包
│   ├── __init__.py
│   ├── main.py                    # CLI 入口
│   ├── cli.py                     # 参数解析
│   ├── parser.py                  # CSV 读取与解析
│   ├── validator.py               # 单条记录校验
│   ├── deduplicator.py            # 重复检测
│   ├── limiter.py                 # 限额校验
│   ├── reporter.py                # 报表生成
│   ├── decimal_utils.py           # 金额精度工具
│   ├── models.py                  # 数据模型
│   └── errors.py                  # 异常类型
└── tests/                         # 自动化测试
    ├── conftest.py
    ├── test_parser.py
    ├── test_validator.py
    ├── test_deduplicator.py
    ├── test_limiter.py
    └── test_reporter.py
```

## 三、安装步骤

### 3.1 克隆/复制项目

```bash
# 项目交付路径固定为 workspace/expense-reporter/
cd workspace/expense-reporter/
```

### 3.2 验证 Python 环境

```bash
python3 --version
# 预期输出：Python 3.8+
```

### 3.3 运行测试（待实现后）

```bash
# 运行全部自动化测试
python3 -m pytest tests/ -v

# 预期：所有测试用例通过
```

## 四、配置说明

### 4.1 限额配置文件（JSON）

可选参数 `--config`，用于类别月度限额配置：

```json
{
  "travel": 5000.00,
  "meal": 2000.00,
  "office": 1000.00,
  "other": 500.00
}
```

**说明**：
- 键为类别名（travel/meal/office/other）
- 值为该类别每月金额上限（单位：元）
- 未配置或配置文件中缺少某类别时，该类别不做限额校验

### 4.2 输入 CSV 格式

```csv
date,employee,category,amount,currency,note
2024-01-15,张三,travel,1200.50,CNY,出差机票
2024-01-16,李四,meal,85.00,CNY,客户招待
```

**表头顺序固定**：date、employee、category、amount、currency、note

## 五、启动与运行

### 5.1 基本用法

```bash
# 完整调用形式
python3 -m expense_reporter input.csv --config limits.json --report report.md

# 最小调用（仅校验，不生成报表）
python3 -m expense_reporter input.csv
```

### 5.2 参数说明

| 参数 | 是否必需 | 默认值 | 说明 |
|------|----------|--------|------|
| `input.csv` | 必需 | - | 输入报销记录 CSV 文件路径 |
| `--config` | 可选 | - | 限额配置文件路径（JSON） |
| `--report` | 可选 | - | 输出 Markdown 报表路径 |
| `--json` | 可选 | - | 输出 JSON 报表路径 |
| `--max-age-days` | 可选 | 365 | 日期校验最大天数 |

### 5.3 退出码说明

| 退出码 | 含义 |
|--------|------|
| 0 | 正常完成且无任何异常记录 |
| 1 | 完成处理但存在解析错误、异常、重复或超限记录 |
| 2 | 输入错误（文件不存在、列缺失、参数非法） |

## 六、常见部署问题

### 6.1 问题：Python 版本过低

**现象**：导入 `dataclasses` 模块失败

**解决**：升级 Python 至 3.8+

```bash
python3 --version
# 如版本低于 3.8，请升级 Python
```

### 6.2 问题：CSV 编码错误

**现象**：解析 UTF-8 BOM 文件失败

**解决**：本项目已支持带或不带 BOM 的 UTF-8 编码，如遇问题请确认文件编码为 UTF-8

### 6.3 问题：金额精度异常

**现象**：浮点数累加出现精度误差

**解决**：本项目内部使用 `Decimal` 类型进行金额计算，确保精度。如自行修改代码，请勿使用 float 聚合金额

## 七、回退方式

如部署后发现问题，可按以下方式回退：

1. **保留原版本**：部署前备份原目录
   ```bash
   cp -r workspace/expense-reporter/ workspace/expense-reporter.backup/
   ```

2. **重新部署**：从备份恢复
   ```bash
   rm -rf workspace/expense-reporter/
   mv workspace/expense-reporter.backup/ workspace/expense-reporter/
   ```

3. **检查测试**：运行测试验证回退版本
   ```bash
   python3 -m pytest tests/ -v
   ```

## 八、后续计划

本项目当前状态：
- ✅ 架构设计完成（TASK-001）
- ❌ 源代码实现未完成
- ❌ 自动化测试未完成
- ❌ README.md 使用文档未完成

**建议**：待代码实现完成后，补充验证本文档中的部署命令，并更新测试证据。

---

**文档版本**：v0.1（架构设计阶段）  
**最后更新**：基于 TASK-001 架构设计文档  
**注意**：本文档中的命令为预期命令，实际部署需待代码实现与测试验证后确认真实性。