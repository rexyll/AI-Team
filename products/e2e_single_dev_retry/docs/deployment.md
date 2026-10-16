

# `stringkit` 部署指引

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | 任意支持 Python 3.7+ 的操作系统（Linux / macOS / Windows） |
| Python 版本 | Python 3.7 及以上 |
| 依赖 | 无外部依赖，仅需 Python 标准库 |

### 验证 Python 版本

```bash
python3 --version
```

预期输出示例：`Python 3.9.0` 或更高版本。

---

## 2. 依赖安装

本项目无第三方依赖，无需安装额外包。

如需要使用 `pytest` 运行测试套件，请执行：

```bash
pip install pytest
```

---

## 3. 获取项目代码

### 方式一：克隆源码仓库

```bash
git clone <repository-url>
cd stringkit
```

### 方式二：解压发布包

```bash
tar -xzf stringkit-*.tar.gz
cd stringkit-*
```

---

## 4. 项目结构

```
stringkit/
├── __init__.py          # 包入口，导出公共 API
├── core.py              # 核心函数实现
├── types.py             # 类型定义与常量
└── tests/
    ├── __init__.py
    └── test_stringkit.py  # 单元测试（21 个用例）
```

---

## 5. 配置说明

本项目为纯函数库，无需配置文件，无需环境变量，无需数据库连接。

直接导入使用即可：

```python
from stringkit import reverse, is_palindrome, count_vowels
```

---

## 6. 运行测试

在项目根目录下执行以下命令验证部署是否成功：

```bash
python -m pytest stringkit/tests/test_stringkit.py -v --tb=short
```

**预期结果：**

```
stringkit/tests/test_stringkit.py: 21 passed in 0.05s
```

所有 21 个测试用例应全部通过，无任何失败或错误。

---

## 7. 使用示例

```python
from stringkit import reverse, is_palindrome, count_vowels

# reverse: 反转字符串
result = reverse("hello")
print(result)  # 输出: olleh

# is_palindrome: 判断回文（忽略大小写和空格）
result = is_palindrome("Never odd or even")
print(result)  # 输出: True

# count_vowels: 统计元音字母
result = count_vowels("hello world")
print(result)  # 输出: 3
```

---

## 8. 常见部署问题与解决

### 问题一：`ModuleNotFoundError: No module named 'stringkit'`

**原因**：当前工作目录不在项目根目录，或 Python 路径未包含项目目录。

**解决**：
```bash
cd /path/to/stringkit
python -m pytest stringkit/tests/test_stringkit.py -v --tb=short
```

### 问题二：`pytest: command not found`

**原因**：未安装 `pytest`。

**解决**：
```bash
pip install pytest
```

### 问题三：测试用例失败

**原因**：代码被修改或环境 Python 版本低于 3.7。

**解决**：
1. 确认 Python 版本 ≥ 3.7
2. 检查 `stringkit/core.py` 是否包含完整实现
3. 恢复原始代码后重新运行测试

---

## 9. 回退方式

如遇部署问题需要回退，执行以下操作：

### 方式一：从 git 恢复

```bash
git checkout HEAD -- .
python -m pytest stringkit/tests/test_stringkit.py -v --tb=short
```

### 方式二：重新解压发布包

```bash
tar -xzf stringkit-*.tar.gz
cd stringkit-*
python -m pytest stringkit/tests/test_stringkit.py -v --tb=short
```

---

## 10. 验收确认

部署完成后，按以下步骤确认交付物完整性：

| 检查项 | 预期结果 | 状态 |
|--------|----------|------|
| Python 版本 ≥ 3.7 | 通过 `python3 --version` 验证 | □ |
| 测试套件全部通过 | 21 passed，0 failed | □ |
| 核心函数可正常导入 | `from stringkit import reverse, is_palindrome, count_vowels` 无报错 | □ |
| 文档齐全 | 包含本部署指引及使用说明 | □ |

---

**文档版本**：v1.0  
**最后更新**：2026-07  
**对应需求编号**：REQ-001 ~ REQ-005