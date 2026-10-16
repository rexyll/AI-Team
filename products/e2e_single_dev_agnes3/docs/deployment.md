

# stringkit 部署指引

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows、macOS、Linux 任意主流发行版 |
| Python 版本 | Python 3.6 或更高版本 |
| 包管理工具 | pip（随 Python 安装附带） |

**验证 Python 版本：**

```bash
python --version
```

输出示例：`Python 3.8.10` 或更高版本即可。

---

## 2. 依赖安装

`stringkit` 为轻量级工具包，无第三方运行时依赖。测试依赖 `pytest`，仅在开发/测试场景需要。

### 2.1 克隆或复制项目

```bash
# 假设项目目录为 stringkit/
cd stringkit/
```

### 2.2 安装 pytest（仅测试需要）

```bash
pip install pytest
```

---

## 3. 配置说明

### 3.1 项目结构

```
stringkit/
├── pyproject.toml          # 项目元数据与构建配置
├── README.md               # 使用说明
└── stringkit/
    ├── __init__.py         # 模块入口，统一导出公开 API
    ├── stringops.py        # 三个核心纯函数实现
    └── tests/
        └── test_stringops.py  # 单元测试（34 个用例）
```

### 3.2 公开 API 导出

模块入口 `__init__.py` 已配置统一的导出列表，外部通过以下方式导入：

```python
from stringkit import reverse, is_palindrome, count_vowels
```

无需修改任何配置文件即可直接使用。

---

## 4. 安装与运行

### 4.1 本地安装（推荐）

在项目根目录执行：

```bash
pip install -e .
```

安装完成后，可在任意 Python 脚本中导入使用：

```python
from stringkit import reverse, is_palindrome, count_vowels

print(reverse("hello"))                                    # 输出: olleh
print(is_palindrome("A man a plan a canal Panama"))        # 输出: True
print(count_vowels("Hello World"))                         # 输出: 3
```

### 4.2 直接运行（无需安装）

若仅需快速验证功能，可直接在 `stringkit/` 目录下运行：

```bash
python -c "from stringkit import reverse, is_palindrome, count_vowels; print(reverse('hello')); print(is_palindrome('A man a plan a canal Panama')); print(count_vowels('Hello World'))"
```

### 4.3 运行单元测试

```bash
python -m pytest stringkit/tests/test_stringops.py -v
```

预期结果：

```
============================= 34 passed in 0.04s =============================
```

---

## 5. 常见部署问题与回退方式

### 5.1 `ModuleNotFoundError: No module named 'stringkit'`

**原因**：包未安装或 Python 解释器路径不包含项目目录。

**解决方式：**
- 确保在 `stringkit/` 项目根目录下执行安装命令
- 或使用可编辑安装：`pip install -e .`

**回退方式：** 删除 Python 环境中的 stringkit 包后重新安装：
```bash
pip uninstall stringkit -y && pip install -e .
```

### 5.2 测试运行后部分用例失败

**原因**：可能使用了未经验证的旧版本代码，或测试环境 Python 版本低于 3.6。

**排查步骤：**
1. 确认 Python 版本 ≥ 3.6
2. 重新安装最新代码后再次运行测试：
```bash
python -m pytest stringkit/tests/test_stringops.py -v
```

**回退方式：** 恢复到已知稳定的历史提交（如适用）：
```bash
git checkout <commit-hash>
pip install -e .
python -m pytest stringkit/tests/test_stringops.py -v
```

### 5.3 `pip` 命令不可用

**原因**：pip 未正确安装或未加入 PATH。

**解决方式：**
```bash
python -m pip install pytest
```

---

## 6. 版本兼容性

| Python 版本 | 兼容性 |
|-------------|--------|
| 3.6+        | ✅ 完全兼容 |
| 3.6 以下    | ❌ 不支持 |

本包所有函数均为纯函数，无全局状态，无外部资源依赖，可安全集成至任何 Python 3.6+ 项目。