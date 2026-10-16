# stringkit 部署指引

> 版本：0.1.0  
> 适用环境：Python 3.9+  
> 最近更新：2025-01-15

---

## 1. 环境要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Python 版本 | ≥ 3.9 | 项目采用现代类型注解（`list[str]` 等），需 3.9+ |
| 操作系统 | Linux / macOS / Windows | 纯 Python 实现，无平台相关依赖 |
| 包管理器 | pip ≥ 21.0 | 支持 PEP 621 (`pyproject.toml`) |
| 构建后端 | setuptools | `pyproject.toml` 中指定 `build-backend = "setuptools.build_meta"` |
| 测试框架 | pytest ≥ 7.0 | 仅作为开发依赖（`dev` extra） |

> **非功能需求来源**：需求规格草案「非功能需求 - 兼容性」与「打包发布」。

---

## 2. 依赖安装步骤

### 2.1 克隆/获取源码
```bash
git clone <repository-url>
cd stringkit
```

### 2.2 创建并激活虚拟环境（推荐）
```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

### 2.3 可编辑安装（开发/部署通用）
```bash
pip install -e .
```
> 实现报告验证命令：`pip install -e .`（TASK-002 测试命令）

### 2.4 安装开发/测试依赖（可选）
```bash
pip install -e ".[dev]"
```
> 将安装 `pytest` 等测试工具，供 CI 或本地验证使用。

---

## 3. 配置说明

本项目为**纯函数工具包**，**无运行时配置文件、环境变量、数据库连接或外部服务依赖**。所有行为由函数参数决定。

| 配置项 | 是否必须 | 说明 |
|--------|----------|------|
| 无 | — | 无需 `.env`、YAML、JSON 等配置文件 |

> 若后续版本引入 CLI 或配置，将在 `CHANGELOG.md` 说明。

---

## 4. 启动/运行命令

### 4.1 运行单元测试（验证部署完整性）
```bash
python -m pytest tests/test_stringkit.py -v
```
> 实现报告验证命令：`python -m pytest tests/test_stringkit.py -v`（TASK-002 测试结果：`17 passed in 0.03s`）

### 4.2 运行测试并生成覆盖率报告
```bash
python -m pytest --cov=stringkit --cov-report=term-missing
```
> 验收标准要求覆盖率 ≥ 90%（需求规格草案 REQ-004）。

### 4.3 在 Python 代码中导入使用
```python
from stringkit import reverse, is_palindrome, count_vowels

reverse("hello")        # -> "olleh"
is_palindrome("A man a plan a canal Panama")  # -> True
count_vowels("aeiouAEIOU")  # -> 10
```

### 4.4 使用 `pipx` 临时运行（无需安装）
```bash
pipx run --spec . stringkit  # 若后续提供 CLI 入口
```
> 当前版本未提供 CLI，`pipx run` 仅作未来扩展参考。

---

## 5. 常见部署问题与回退方式

| 现象 | 可能原因 | 排查/解决步骤 | 回退方式 |
|------|----------|---------------|----------|
| `pip install -e .` 报错 `ERROR: Could not find a version that satisfies the requirement setuptools` | pip 版本过老 | `pip install --upgrade pip setuptools wheel` 后重试 | 使用系统自带 `python -m pip install --upgrade pip` |
| `python -m pytest` 提示 `ModuleNotFoundError: No module named 'pytest'` | 未安装测试依赖 | `pip install -e ".[dev]"` 或 `pip install pytest` | — |
| 导入报错 `ModuleNotFoundError: No module named 'stringkit'` | 未在正确环境安装/未激活虚拟环境 | 确认 `pip list | grep stringkit` 显示 `0.1.0`；重新 `pip install -e .` | 删除 `.venv` 重建虚拟环境 |
| 测试失败（非 17 passed） | 代码被意外修改/版本不匹配 | `git status` 检查变更；`git stash` 暂存本地改动后重新测试 | `git checkout -- .` 恢复到最后提交 |
| 类型检查报错（`mypy --strict`） | Python 版本 < 3.9 或类型注解不兼容 | 升级 Python ≥ 3.9；或将 `list[str]` 改为 `List[str]`（需 `from typing import List`） | 降级到兼容的类型注解写法 |

### 5.1 完整回退流程（回滚到干净状态）
```bash
# 1. 停止所有相关进程
# 2. 删除虚拟环境
rm -rf .venv

# 3. 清理 pip 缓存（可选）
pip cache purge

# 4. 重新克隆/检出已知良好标签
git fetch --tags
git checkout v0.1.0  # 或对应发布标签

# 5. 重新按 2.2~2.3 步骤部署
```

---

## 6. 附录：验收清单（对应需求规格草案）

| 验收项 | 命令 | 通过判据 |
|--------|------|----------|
| 可编辑安装成功 | `pip install -e .` | 无报错，`pip list` 显示 `stringkit 0.1.0` |
| 单测全通过 | `python -m pytest tests/test_stringkit.py -v` | `17 passed`，退出码 0 |
| 覆盖率 ≥ 90% | `python -m pytest --cov=stringkit` | `TOTAL` 行覆盖率 ≥ 90% |
| 函数签名可用 | `python -c "from stringkit import reverse, is_palindrome, count_vowels; print(reverse('abc'))"` | 输出 `cba` 无异常 |

---

> **文档维护**：本指引随版本发布同步更新，变更记录见 `CHANGELOG.md`。