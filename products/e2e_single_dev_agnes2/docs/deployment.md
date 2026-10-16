

# stringkit 部署指引

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | 任意支持 Python 3.6+ 的平台（Windows / macOS / Linux） |
| Python 版本 | ≥ 3.6（推荐 3.8 及以上） |
| 外部依赖 | **无**，仅使用 Python 标准库 |
| 测试框架 | `pytest`（可选，用于运行单元测试套件） |

> **注意**：本工具包不引入任何第三方依赖，部署时只需确保系统已安装符合版本要求的 Python 解释器。

---

## 2. 依赖安装步骤

### 2.1 验证 Python 环境

```bash
python --version
```

预期输出包含 `Python 3.6.x` 或更高版本。若未安装 Python，请访问 [python.org](https://www.python.org/downloads/) 下载安装。

### 2.2 安装 pytest（可选）

```bash
pip install pytest
```

> `pytest` 仅用于运行单元测试套件，不影响工具包本身的正常使用。

---

## 3. 配置说明

本项目**无需额外配置文件**。工具包行为由源码内部逻辑控制，不涉及环境变量、配置文件或数据库连接等外部配置项。

### 目录结构

部署后项目目录结构如下：

```
stringkit/
├── __init__.py          # 公共入口，导出三个函数
├── core.py              # 核心函数实现
└── tests/
    └── test_stringkit.py   # 单元测试套件（42 个用例）
README.md
```

### 安装方式

将项目代码克隆或复制到目标机器即可使用：

```bash
git clone <repository-url>
cd stringkit
```

无需执行 `pip install`，因为本项目无第三方依赖，可直接作为模块导入。

---

## 4. 启动与运行

### 4.1 导入使用

```python
from stringkit.core import reverse, is_palindrome, count_vowels

# reverse
print(reverse("hello"))        # 输出: olleh

# is_palindrome
print(is_palindrome("A man a plan a canal Panama"))  # 输出: True

# count_vowels
print(count_vowels("hello world"))  # 输出: 3
```

也可通过 `__init__.py` 导出的公共接口使用：

```python
from stringkit import reverse, is_palindrome, count_vowels
```

### 4.2 运行单元测试

```bash
python -m pytest tests/test_stringkit.py -v
```

**预期结果**：

```
42 passed in 0.06s
```

全部 42 个测试用例均应通过，覆盖 `reverse`、`is_palindrome`、`count_vowels` 三个函数的正常场景、边界条件及异常输入。

---

## 5. 常见部署问题

### 问题 1：`ModuleNotFoundError: No module named 'stringkit'`

**原因**：项目路径未加入 Python 的模块搜索路径。

**解决**：确保在包含 `stringkit/` 目录的父目录下运行脚本，或将项目根目录添加到 `PYTHONPATH`：

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### 问题 2：传入非字符串参数时行为异常

**原因**：函数签名期望 `str` 类型输入，传入 `None` 或其他类型可能引发意外错误而非明确的 `TypeError`。

**解决**：调用前对入参进行类型校验，或升级至最新代码版本（已包含类型检查逻辑）。

### 问题 3：`pytest` 命令未找到

**原因**：未安装 `pytest` 或当前环境中 `pip` 与 `python` 版本不一致。

**解决**：
```bash
python -m pip install pytest
python -m pytest tests/test_stringkit.py -v
```

---

## 6. 回退方式

本项目无持久化状态，无数据库迁移，无服务进程，回退操作极简：

1. **覆盖源码**：用旧版本代码直接替换当前目录下的文件即可回退。
2. **重新克隆**：若需恢复到特定提交，使用版本控制工具（如 Git）检出对应版本：

```bash
git checkout <commit-hash>
```

3. **验证回退结果**：重新运行测试套件确认功能正常：

```bash
python -m pytest tests/test_stringkit.py -v
```

---

> **文档版本**：v1.0  
> **基于上下文**：需求规格草案 REQ-001 ~ REQ-005、TASK-002 实现报告、TASK-003 测试报告、TASK-004 文档报告  
> **测试证据引用**：`42 passed in 0.06s`（TASK-004）