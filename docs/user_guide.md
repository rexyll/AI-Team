# AI-Team 使用说明书（User Guide）

> 适用版本：`v0.9.0-rc`
> 本手册描述如何使用 Agnes 大模型真实运行一次 AI 开发团队，从用户需求到可检验的交付物。

---

## 1. 这是什么

AI-Team 是一个由五个角色组成的 AI 软件开发团队运行时：

```
你的需求 → Planner(拆解计划) → Architect(设计) → Developer(编码)
                              → Tester(测试) → Reviewer(审核/返工) → 项目结果
```

你只需要在命令行给出一句话需求，团队将自动完成计划、设计、编码、测试与审核的完整闭环。所有角色默认通过 Agnes 大模型驱动。

---

## 2. 环境准备

### 2.1 硬性要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 11 | 官方支持环境 |
| Python | **3.14** | 硬性要求，3.13 及以下无法导入（详见 production_configuration.md §1） |
| 终端 | PowerShell | 所有命令以仓库根为工作目录 |

### 2.2 安装依赖

```powershell
cd F:\workspace\_coding_workspace\AI-Team\ai-dev-team
python -m venv .venv            # 首次
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2.3 确认基线健康

首次真实运行前，先确认契约测试全绿（约 17 秒，无需网络）：

```powershell
pytest -q
```

预期末行形如 `931 passed` 且无 `failed`、无 warning 汇总。这是后续判断"问题来自环境还是模型"的基准线。

---

## 3. 配置大模型（多 Provider，按角色绑定）

### 3.1 创建 `.env` 文件

在**仓库根目录**创建 `.env`（已被 gitignore，不会入库）。模板见 `.env.example`。通过 OpenRouter 使用 Ox Alpha 的最小配置：

```ini
OPENROUTER_API_KEY=sk-or-v1-你的密钥
DEFAULT_PROVIDER=openrouter

# 五个角色统一用 Ox Alpha（也可逐角色换成其他 slug）
PLANNER_MODEL=stealth/ox-alpha
ARCHITECT_MODEL=stealth/ox-alpha
DEVELOPER_MODEL=stealth/ox-alpha
TESTER_MODEL=stealth/ox-alpha
REVIEWER_MODEL=stealth/ox-alpha
```

模型 slug 从 [openrouter.ai/models](https://openrouter.ai/models) 页面复制。混合搭配示例（Planner/Reviewer 用强模型、Tester 用便宜档）同样只需改这几行。

### 3.2 验证配置

```powershell
python -c "from config.model import resolve_role_llm_spec; print([resolve_role_llm_spec(r) for r in ('planner','developer')])"
```

输出各角色绑定的 `(provider, model)` 即为解析成功（此步不发网络请求、不需要密钥）。真实调用时的密钥校验发生在首次请求：

```powershell
python -c "from config.model import get_client_for; get_client_for('openrouter'); print('openrouter config OK')"
```

> 说明：provider 客户端为**惰性构造**——导入与对象构造都不需要密钥；每个 provider 一个独立缓存客户端，缺密钥时在首次真实使用处报 `RuntimeError` 并指明变量名。

---

## 4. 第一次真实运行

### 4.1 运行前检查清单

Developer 的所有文件操作都发生在**仓库之外的独立工作区**：
`F:\workspace\_coding_workspace\AI-Team\projects\`（由 `security/workspace.py` 定义，与代码仓库物理隔离，详见 §6.1）。

运行前建议清理上次实验的残留，避免旧文件干扰模型的探索：

```powershell
Get-ChildItem F:\workspace\_coding_workspace\AI-Team\projects
# 需要时删除指定实验目录（不影响 git 仓库）
Remove-Item -Recurse -Force F:\workspace\_coding_workspace\AI-Team\projects\<实验名>
```

### 4.2 选择第一个需求

原则：**单任务、小工具、零外部依赖**。推荐首个需求：

```powershell
python main.py "开发一个摄氏度转华氏度的Python命令行小工具，所有文件放在 workspace/demo01/ 目录下，完成后运行它验证正确性"
```

> 经验：在需求里明确指定"文件放在 `workspace/xxx/` 子目录"，可以让产物集中、便于清理（仓库已内置空的 `workspace/` 目录）。

### 4.3 解读运行输出

一次典型运行的输出结构：

```text
============================================================
AI TEAM START
============================================================
TASK-001 | architect | 设计温度转换模块        ← Planner 拆解出的任务逐个执行
[Completed] TASK-001 (completed)
TASK-002 | developer | 实现温度转换功能       ← Developer 开始工作
[Tool] write_file                            ← Developer 的真实工具调用
[Args] {'path': 'workspace/demo01/converter.py', ...}
[Result] ...
[Tool] run_command                           ← 运行验证命令
[Completed] TASK-002 (completed)
TASK-003 | tester | ...                      ← 测试与审核（若计划包含）
============================================================
FINAL TASK STATUS
============================================================
TASK-001   completed   architect   ...
TASK-002   completed   developer   ...
```

全部任务 `completed` 即执行成功。随后**亲自验收产物**：

```powershell
git status --short                # 查看新增了哪些文件
Get-Content workspace/demo01/*.py # 人工阅读生成的代码
python workspace/demo01/converter.py 100   # 亲手跑一遍
```

---

## 5. 评估维度（真实测试要看什么）

| 维度 | 观察点 |
|---|---|
| 计划质量 | 任务拆分是否合理、粒度是否恰当、依赖关系是否正确 |
| 架构质量 | Architect 输出的设计是否对 Developer 有实际指导作用 |
| 编码能力 | 生成的代码能否直接运行、是否遵守"最小修改"原则 |
| 自主验证 | Developer 是否主动 run_command 运行了程序/测试 |
| 质量门禁 | Tester 是否给出 TEST_PASSED/FAILED 的真实判断 |
| 审核闭环 | Reviewer 是否 APPROVED；若 REVISION_REQUIRED 是否有效返工 |

建议把每次运行的完整 stdout 重定向存档，便于横向对比不同模型/提示词版本：

```powershell
python main.py "..." *>&1 | Tee-Object -FilePath runs\run-01.log
```

---

## 6. 已知边界（务必了解）

### 6.1 工作区与仓库物理隔离

Developer 的文件工具受 sandbox 保护，授权根目录是 `AI-Team\projects\`——**仓库的兄弟目录**，而非仓库本身（定义见 `security/workspace.py` 的 `PROJECT_ROOT`）。因此：

- 生成的代码**天然不会进入 git 仓库**，无需担心污染版本库；
- 需求中写的相对路径（如 `workspace/demo01/converter.py`）都落在 `projects\` 内部；
- 逃逸出该根目录的路径会被拒绝（有安全契约守卫）；
- 实验产物按目录归档管理，用完可整目录删除。

### 6.2 CLI 运行是"即时性"的

当前 `main.py` 不会把事件流/项目快照落盘（内存态执行）。如需体验持久化→恢复→审计链路，运行自带示例：

```powershell
python examples/persistence_recovery.py
```

### 6.3 内置的自动重试预算

| 机制 | 上限 | 触发时表现 |
|---|---|---|
| Planner 计划修复重试 | 2 次（共 3 次尝试） | 模型返回非法计划 JSON 时自动携带错误重试 |
| Reviewer 返工循环 | 3 轮 | REVISION_REQUIRED 时 Developer 自动返工 |
| Developer 工具循环 | 50 步 | 超限报 RuntimeError |

### 6.4 费用与时长

一次完整运行 = 5 类角色 × 若干次模型调用（Developer 还有多次工具往返）。小型项目通常数分钟内完成；请从小需求起步，观察费用曲线后再加大规模。

---

## 7. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `RuntimeError: AGNES_API_KEY is not configured.` | `.env` 缺失/键名错误，且发生在首次真实调用时 | 检查 `.env`（§3.1），重新运行 |
| `[ERROR] ValueError: Planner 在多次尝试后仍无法生成合法计划` | 模型连续 3 次产不出合法计划 JSON | 换更明确的需求措辞重试；或检查 `AGNES_MODEL` 是否指向具备 JSON 输出能力的模型 |
| `Tester execution failed: ...` | Tester 阶段异常，错误信息会携带真实原因 | 若提示判定词缺失等解析问题，说明模型输出完全不含结论词，换模型或简化任务；实现类问题按 DevPlan 立项 |
| 卡在 Developer 阶段很久 | 工具循环接近 50 步上限 | 属正常重试行为；若频繁出现，说明任务对当前模型过难，缩小需求 |
| Tester 反复 TEST_FAILED | 质量门禁真实生效 | 查看任务 error 字段与产物代码，判断是模型能力还是需求歧义 |
| 连接超时/401 | BASE_URL 或密钥无效 | 用 §3.2 的验证命令隔离排查 |
| 中文乱码 | 控制台编码 | `chcp 65001` 后重试 |

---

## 8. 与开发流程的关系

- 本手册对应的运行时契约由 `tests/test_production_configuration_contract.py`、`tests/test_release_readiness_smoke_contract.py` 等守卫；文档、契约与实现三者须同节点变更。
- 真实运行中发现的行为问题，请按 DevPlan 流程立项修复，不要绕过安全层（权限策略、sandbox）临时应付。
