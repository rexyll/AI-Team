

# stringkit 部署指引

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | 任意支持 Python 3.6+ 的操作系统（Windows / macOS / Linux） |
| Python 版本 | Python 3.6 或更高版本 |
| 包管理器 | `pip`（随 Python 安装自带，建议版本 ≥ 20.3） |
| 第三方依赖 | 无（纯 Python 标准库实现） |
| 内存占用 | 可忽略（纯函数，无状态） |

---

## 2. 依赖安装步骤

本项目为纯 Python 包，**无需安装任何第三方依赖**。仅需确保环境中存在 Python 3.6+ 及 `pip`。

```bash
# 验证 Python 版本
python --version
# 输出示例：Python 3.10.12

# 验证 pip 可用
pip --version
# 输出示例：pip 23.2.1 from ... (python 3.10)
```

---

## 3. 配置说明

### 3.1 项目结构

```
stringkit/
├── stringkit/
│   ├── __init__.py       # 包入口，导出公共 API
│   ├── stringkit.py      # 核心函数实现
│   ├── test_stringkit.py # 单元测试
│   └── usage.md          # 使用说明文档
└── README.md             # 项目说明
```

### 3.2 安装方式

#### 方式一：直接克隆到项目中（推荐用于开发集成）

将 `stringkit` 目录整体复制到项目的依赖路径中：

```bash
# 假设项目根目录为 PROJECT_ROOT
cp -r ./stringkit/stringkit /path/to/your/project/dependencies/
```

然后在代码中直接引用：

```python
from dependencies.stringkit import reverse, is_palindrome, count_vowels
```

#### 方式二：通过 `pip` 安装（如后续补充 `setup.py` 或 `pyproject.toml`）

当前版本为开发阶段，尚未发布至 PyPI。若后续生成打包文件，可使用：

```bash
pip install ./stringkit
```

### 3.3 环境变量

本项目**无环境变量配置项**，所有函数行为仅由输入参数决定。

---

## 4. 启动 / 运行命令

### 4.1 使用函数

```python
import stringkit

# 反转字符串
result = stringkit.reverse("hello")
print(result)  # 输出：olleh

# 判断回文
is_pal = stringkit.is_palindrome("A man a plan a canal Panama")
print(is_pal)  # 输出：True

# 统计元音字母
vowel_count = stringkit.count_vowels("AEIOU")
print(vowel_count)  # 输出：5
```

### 4.2 执行单元测试

根据 TASK-002 验证结果，使用以下命令运行全部测试用例：

```bash
python -m pytest stringkit/stringkit/test_stringkit.py -v
```

**预期输出**（21 个用例全部通过）：

```
stringkit/stringkit/test_stringkit.py::test_reverse_empty PASSED        [  4%]
stringkit/stringkit/test_stringkit.py::test_reverse_single PASSED       [  9%]
stringkit/stringkit/test_stringkit.py::test_reverse_normal PASSED       [ 14%]
...
21 passed in 0.03s
```

---

## 5. 常见部署问题与回退方式

### 问题一：`ModuleNotFoundError: No module named 'stringkit'`

**原因**：Python 解释器无法找到 `stringkit` 包所在目录。

**解决方法**：
```bash
# 检查当前 Python 路径
python -c "import sys; print(sys.path)"

# 确认 stringkit 目录位于上述路径之一，或通过 PYTHONPATH 临时添加
export PYTHONPATH="${PYTHONPATH}:/path/to/stringkit"
```

**回退**：移除环境变量设置，确认 `stringkit` 目录已正确放置。

---

### 问题二：测试执行失败

**原因**：可能修改了 `test_stringkit.py` 后未同步更新，或 pytest 未正确安装。

**解决方法**：
```bash
# 确认 pytest 已安装
pip install pytest

# 重新运行测试
python -m pytest stringkit/stringkit/test_stringkit.py -v
```

**回退**：从版本控制恢复原始的 `test_stringkit.py` 文件，确保测试用例与实现保持同步。

---

### 问题三：导入时出现循环导入错误

**原因**：`__init__.py` 中导出语句配置不当。

**解决方法**：确认 `stringkit/__init__.py` 内容如下：

```python
from .stringkit import reverse, is_palindrome, count_vowels
```

**回退**：检查 `stringkit.py` 中函数定义是否存在，确保导入路径正确。

---

### 问题四：Python 版本不兼容

**原因**：目标环境 Python 版本低于 3.6。

**解决方法**：升级 Python 环境：
```bash
# Ubuntu/Debian
sudo apt-get install python3.10

# macOS (Homebrew)
brew install python@3.10
```

**回退**：在兼容环境中重新部署，或降级项目源码以支持更低版本（需修改代码语法）。

---

## 6. 附录

| 需求编号 | 关联部署项 |
|----------|------------|
| REQ-001 ~ REQ-003 | 核心函数实现（`stringkit.py`） |
| REQ-004 | 单元测试（`test_stringkit.py`，21 个用例已通过） |
| REQ-005 | 使用说明文档（`usage.md`） |

---

**文档版本**：v1.0  
**基于上下文版本**：TASK-002 实现报告及测试证据（21 passed）