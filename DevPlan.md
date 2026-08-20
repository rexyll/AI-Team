# AI-Team 开发计划与开发历史

> **项目：** `rexyll/AI-Team`
>
> **文档用途：** 本文件是 AI-Team 的开发状态账本（Development Ledger）。每完成一个独立功能、架构阶段或重要修复，必须记录状态、验收结果、测试数量、Git commit 与经验，避免重复设计和重复修复已经解决的问题。
>
> **DevPlan 来源：** 本文件基于 `docs/devplan` 分支中的 `DevPlan.md`（blob `e856d13a0183de43b5e16e1e00df39d0374072ee`）同步到 `refactor/runtime-architecture` 后更新。

---

# 1. 当前项目状态

## 1.1 当前分支

- Branch: `refactor/runtime-architecture`
- 当前 HEAD: `7bb371be68a9b2c9c9c94026efd06928b8e6817f`
- Commit: `fix: complete AgentResult compatibility contract`
- 工作树：用户本地已确认 clean

## 1.2 当前测试基线

用户本地最新执行：

```text
pytest -q

307 passed in 19.86s
```

**当前稳定基线：307 passed，0 failed。**

此前基线为 299 passed；AgentResult Contract 迁移和兼容性修复后新增/恢复了相关测试，因此当前应以 **307 passed** 作为后续所有重构的回归基线。

## 1.3 当前阶段

**当前处于：Phase 2 — AgentResult Contract 统一化阶段的收尾，并准备进入 Phase 3 AgentContext 正式化。**

已经完成 Architect / Developer / Tester / Reviewer 的 AgentResult 统一返回契约，以及 AgentResult 的 legacy status / legacy payload 兼容。

当前尚未完成的是 Developer Result 的进一步结构化，以及 AgentContext 从 Task 内部结构向稳定 read-only contract 的完整迁移。

---

# 2. 总体开发目标

AI-Team 的最终目标不是简单顺序调用几个 Agent，而是构建一个：

- 可测试
- 可恢复
- 可扩展
- 可替换 LLM
- 具备安全 Tool/Sandbox
- 具备明确 Task / Agent / Project Contract
- 支持依赖调度与未来并行执行
- 具备持久化与可观测性

的 AI 软件开发团队 Runtime。

目标架构：

```text
User Request
    ↓
Planner
    ↓
PlanBuilder
    ↓
DependencyGraph
    ↓
ProjectOrchestrator
    ↓
TaskWorkflow
    ↓
AgentContext
    ↓
Agent
    ↓
AgentResult
    ↓
Tester
    ↓
Reviewer
    ↓
ProjectResult
```

质量门禁必须保持：

```text
Developer
   ↓
Tester
   ├── failed → Developer revision
   └── passed → Reviewer
                    ├── revision → Developer
                    └── approved → Complete
```

---

# 3. 已完成开发阶段

## Phase 0 — 基础项目骨架与 Agent 原型

### <span style="color:green">√</span> 0.1 多 Agent 基础结构

已建立 `agents/` 与 `runtime/` 基础目录，形成 Planner / Architect / Developer / Tester / Reviewer，以及 Task / Workflow / Router / Factory 等 Runtime 基础模块。

### <span style="color:green">√</span> 0.2 Developer Agent + Workspace Sandbox

Developer 已具备受保护工作区操作能力，通过工具注册表执行文件读取、修改、测试和构建。

关键原则：

- Agent 只能操作受保护工作区。
- 读取文件优先使用文件工具。
- `run_command` 主要用于测试、构建和专用开发工具。
- 修改代码前必须读取相关文件。
- Developer Tool Loop 有最大迭代次数。

关键 commits：

- `f9c42858fa3523b000428ff53bc6126bdd88ecac` — feat: establish developer agent with workspace sandbox
- `60ac4e8cea7986735e0d44fdb55e1cf9a92ea1a7` — feat: establish developer agent with workspace sandbox
- `c9b02371389440926e667a73388ed837f5cace9f` — fix: pass reviewer feedback into developer context and bound tool loop
- `1e8255d471396b3a49ca1c7184d5e9b35c4f1709` — fix: correct terminal command policy pattern

### <span style="color:green">√</span> 0.3 TaskManager / Workflow 基础能力

TaskManager 已成为 Task 状态变更的核心入口；Workflow 负责 orchestration，Agent 负责执行。

关键 commits：

- `75fcfe77746302d8f623e60052acd4b9adaddf78` — fix: keep task state transitions inside TaskManager
- `dfb21a515c3f6896530f167bcf49332d63657b34` — fix: centralize workflow execution and robust failure handling
- `7592dbeece2d14f9fea9a7bd21dbe568401dc2f2` — refactor: route developer tasks through TaskWorkflow
- `43108ad45f271f117a298b90d8414c56b313061d` — refactor: centralize workflow state transitions and review history

---

# 4. Phase 1 — Task Lifecycle / Quality Gate / Workflow 稳定化

### <span style="color:green">√</span> 1.1 Task 生命周期

核心状态：

```text
pending → ready → running → reviewing → review_pending → completed
```

失败/返工路径：

```text
Developer → Tester FAILED → Developer revision → Tester
```

```text
Developer → Tester PASSED → Reviewer REVISION → Developer revision → Tester → Reviewer
```

### <span style="color:green">√</span> 1.2 Tester Quality Gate

Reviewer 只有在 Tester 明确返回 `passed` 时才能运行；Tester `failed` 必须回到 Developer。

关键 commits：

- `7b1e78b06e45280ce2ad4c8b5a4049f044b01936` — feat: add dedicated tester agent
- `458f80504da4b4f116249e776593013619cf2cc7` — feat: register tester agent
- `9ce87012603ac851f13611dc63416df2f9faf825` — fix: enforce developer tester reviewer quality gate
- `63eea6c37c995b167e1fd3431b10c01c9555bae7` — fix: restore tester workflow execution

### <span style="color:green">√</span> 1.3 Reviewer Revision Loop

支持 `APPROVED` / `REVISION_REQUIRED`，并受 `max_review_rounds` 限制。

关键 commits：

- `f8d8e2f24913f85c24cd7793bdc4febaaeac755c` — feat: add structured review history to task model
- `0d57e82c5c9942ceeeae552af10dc7f75d21423c` — refactor: simplify workflow result handling

### <span style="color:green">√</span> 1.4 Tester / Reviewer History

Task 已支持：

- `test_result`
- `test_history`
- `review_result`
- `review_history`

并覆盖重复结果、revision round、history 保留等语义。

### <span style="color:green">√</span> 1.5 Workflow Result Handling 收敛

Tester / Reviewer result handling 已从主流程中抽离。

经验：曾出现 Workflow 简化后 Tester 执行链路被绕过的问题，后续通过 `63eea6c...` 恢复。因此以后 Workflow 重构必须优先执行完整 Developer → Tester → Reviewer 集成测试。

---

# 5. Phase 1.5 — Dependency / Context Architecture

### <span style="color:green">√</span> 1.6 Task Dependency Graph

支持 Task dependencies，并拒绝循环依赖。

commit：

- `4584078663bd8dc8b056a8d7599dc950ffc338b0` — feat: reject cyclic task dependencies

### <span style="color:green">√</span> 1.7 ContextBuilder

`runtime/context_builder.py` 已建立，负责：

- 暴露已完成 dependency result
- 暴露 Tester feedback
- 暴露 Reviewer feedback
- 不修改 Task
- 不改变 Task status
- 不执行 Agent
- 不负责 Workflow transition

关键 commits：

- `ffad04127062dab03bb192e3cf0dbfa46092baa7` — fix: preserve legacy task context API
- `5a860447d95fb87da5d56c4f7efbf50e11e95f15` — add context flow integration tests

### <span style="color:green">√</span> 1.8 Reviewer Feedback → Developer Context

Reviewer revision 后的 feedback 能重新进入 Developer context。

commit：`c9b02371389440926e667a73388ed837f5cace9f`

---

# 6. Phase 1.6 — Project Planning / Orchestration

### <span style="color:green">√</span> 1.9 Planner / PlanBuilder / Project Execution

已形成 Project Plan → Task → dependency → execution 基础链路，并有 Project Execution 测试。

commit：

- `e2d31f3fc0e5e9873893dd69f786994411b03b35` — fix project execution test orchestrator

### <span style="color:green">√</span> 1.10 Agent Factory / Registry / Configuration

已有：

- `runtime/agent_factory.py`
- `runtime/agent_registry.py`
- `runtime/agent_config.py`

关键 commits：

- `529ca53c004fb30569e935e58a6419461f7167a0` — feat: add centralized task workflow factory
- `79413eb445c1951d6d33948c23df09e11551ecb8` — fix agent factory custom configuration validation

---

# 7. Phase 2 — AgentResult Contract 统一化

### <span style="color:green">√</span> 2.1 建立 AgentResult

统一结果模型：

```python
AgentResult(
    status,
    agent,
    task_id,
    message,
    data,
)
```

commit：

- `3d9f2e3599774b4ca4e9184107f6419ccc4176ee` — feat: canonicalize agent results

### <span style="color:green">√</span> 2.2 Legacy Status Compatibility

```text
architect_completed → completed
developer_completed → completed
tester_passed       → passed
tester_failed       → failed
reviewer_approved   → approved
reviewer_revision   → revision
```

### <span style="color:green">√</span> 2.3 Legacy Payload → data

旧 Agent-specific payload 已归一化到 `data`，同时保持 legacy payload 可通过 `result[key]` / `result.get(key)` 访问。

关键 commit：

- `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` — update code

### <span style="color:green">√</span> 2.4 Runtime Result Normalizer

已建立 `runtime/result_normalizer.py`，统一把 AgentResult / dict 转换为 AgentResult。

### <span style="color:green">√</span> 2.5 所有 Agent 正式返回 AgentResult

当前 Architect / Developer / Tester / Reviewer 已统一使用 AgentResult。

本阶段最终 commit：

- `7bb371be68a9b2c9c9c94026efd06928b8e6817f` — `fix: complete AgentResult compatibility contract`

该 commit 包含：

- Architect `run()` 返回 `AgentResult`
- Developer `run()` 返回 `AgentResult`
- BaseAgent `run()` 明确返回 `AgentResult`
- AgentResult compatibility API 修复
- AgentResult legacy payload 直接访问兼容
- 相关测试修复与补充

### <span style="color:green">√</span> 2.6 BaseAgent 类型契约

`agents/base.py` 已明确：

```python
def run(self, task: Task) -> AgentResult:
    ...
```

### <span style="color:green">√</span> 2.7 AgentResult 辅助 API

已完成并测试：

```python
AgentResult.from_any(...)
result.succeeded
result.failed
result.requires_revision
```

特别修复了此前由于缩进导致 `from_any` / properties 落在类外的问题。

### ☐ 2.8 Developer Result 完整结构化

**当前未完全完成。**

Developer 当前已经保证 `message` 为字符串，但最终业务结果仍可以进一步结构化到：

```python
AgentResult(
    status="completed",
    agent="developer",
    task_id=task.id,
    message="Implementation completed successfully.",
    data={
        "report": "...",
        "files_changed": [...],
        "tests": {...},
    },
)
```

下一步需要定义 DeveloperResult data schema，并同步 Workflow / Context / tests。

---

# 8. Phase 3 — AgentContext 正式化

### ☐ 3.1 Task → AgentContext

目标：

```text
Task
 ↓
ContextBuilder
 ↓
AgentContext
 ↓
Agent
```

`runtime/agent_context.py` 已存在，包含：

- task_id
- task_title
- task_description
- role
- status
- review_round
- dependencies
- task_result
- tester_feedback
- reviewer_feedback
- history
- metadata

下一阶段要让 Agent 真正消费稳定的 read-only context，而不是直接依赖 Task 内部结构。

### ☐ 3.2 Context Snapshot 完整化

必须保持：

- Agent 不修改原 Task
- dependency context 是 snapshot
- 未完成 dependency 不暴露给下游 Agent
- Tester / Reviewer 只获得执行所需信息

### ☐ 3.3 Context History

统一暴露 Task execution history、test history、review history，避免各 Agent 自己拼接历史。

---

# 9. Phase 4 — LLM Abstraction

当前存在：

```text
runtime/llm/base.py
runtime/llm/mock.py
```

但 Agent 仍有直接依赖 `config.model.ask_ai` 或 OpenAI-compatible SDK 的情况。

### ☐ 4.1 BaseLLM 完整实现

### ☐ 4.2 MockLLM

必须支持完全离线 Agent 测试。

### ☐ 4.3 Provider Adapter

目标：

```text
Agent → BaseLLM → Provider Adapter → LLM API
```

### ☐ 4.4 Prompt / Model / Runtime 配置化

统一管理：

- model
- system prompt
- temperature
- max tokens
- timeout
- retry

---

# 10. Phase 5 — Tool / Sandbox Architecture

目标：

```text
Agent
 ↓
ToolExecutor
 ↓
ToolGuard
 ↓
Sandbox
 ↓
Tool
```

### ☐ 5.1 ToolExecutor
### ☐ 5.2 Tool Policy

权限原则：

```text
Architect → read-only / no command
Developer → read/write + test/build
Tester    → read/test
Reviewer  → read-only
Planner   → planning tools
```

### ☐ 5.3 Workspace Sandbox 强化

- 工作区边界
- 路径规范化
- 禁止目录逃逸
- 命令策略
- Tool 参数校验
- 错误隔离

### ☐ 5.4 Tool Loop Reliability

增加 timeout、repeated-call detection、invalid argument handling、result size limit、cancellation。

---

# 11. Phase 6 — Project Orchestrator

### ☐ 6.1 Project Execution State

```text
created → planning → planned → executing → completed / failed / blocked
```

### ☐ 6.2 Dependency-aware Scheduling

只有依赖全部完成的 Task 才进入 ready。

### ☐ 6.3 并行执行

无依赖 Task 后续支持并行。

### ☐ 6.4 Failure Recovery

区分：

- Agent business failure
- Tester failure
- Reviewer revision
- Tool failure
- LLM failure
- Runtime exception
- Dependency failure

### ☐ 6.5 ProjectResult

最终统一：

```python
ProjectResult(
    status=...,
    project_id=...,
    summary=...,
    tasks=...,
    failures=...,
    metadata=...,
)
```

---

# 12. Phase 7 — Persistence / Observability

### ☐ 7.1 Execution Persistence

保存 project、plan、task、state history、AgentResult、AgentContext snapshot、tool calls、errors。

### ☐ 7.2 Event Log

统一事件：

```text
ProjectCreated
PlanCreated
TaskReady
TaskStarted
AgentStarted
AgentCompleted
TestPassed
TestFailed
ReviewApproved
ReviewRevision
TaskCompleted
TaskFailed
```

### ☐ 7.3 Structured Logging

统一字段：

```text
project_id
task_id
agent
stage
status
round
timestamp
```

---

# 13. Phase 8 — Production Hardening

### ☐ 8.1 Retry / Timeout
### ☐ 8.2 Cancellation
### ☐ 8.3 Concurrency Control

限制 Agent / Tool / LLM / Project 并发。

### ☐ 8.4 Security Audit

重点：

- path traversal
- command injection
- prompt injection
- secret leakage
- tool privilege escalation
- workspace escape

### ☐ 8.5 Full Regression Suite

每个阶段必须执行：

```powershell
pytest -q
```

并把通过数量记录到 DevPlan.md。

---

# 14. 已验证的重要问题与经验

## 14.1 Task 状态必须由 TaskManager 管理

结论：

> **TaskManager 管状态，Workflow 管流程，Agent 管执行。**

commit：`75fcfe77746302d8f623e60052acd4b9adaddf78`

## 14.2 Tester 必须是 Reviewer 前的质量门禁

结论：

> Reviewer 不能替代 Tester；Tester failed 必须回到 Developer。

commits：

- `63eea6c37c995b167e1fd3431b10c01c9555bae7`
- `9ce87012603ac851f13611dc63416df2f9faf825`

## 14.3 Legacy API 不要无条件删除

ContextBuilder 保留旧 `build_task_context(task, all_tasks)`，新代码使用 `ContextBuilder(all_tasks).build(task)`。

commit：`ffad04127062dab03bb192e3cf0dbfa46092baa7`

## 14.4 AgentResult 必须兼容历史 Agent

使用 `LEGACY_STATUS_MAPPING` + legacy payload normalization，而不是一次性删除历史 contract。

commits：

- `3d9f2e3599774b4ca4e9184107f6419ccc4176ee`
- `6528bf27e4a820c1eea2f0a98d1030e4c47f6599`
- `7bb371be68a9b2c9c9c94026efd06928b8e6817f`

## 14.5 AgentResult 类内方法必须检查缩进

曾出现 `from_any`、`succeeded`、`failed`、`requires_revision` 因缩进落到类外，导致 API 实际不可用。

以后新增 dataclass method/property 必须配套测试。

## 14.6 `AgentResult.from_dict()` 与直接构造的契约不能混淆

当前语义：

- 直接构造：允许 `agent=None`、`task_id=None`，用于 Runtime Contract 的部分结果对象。
- `from_dict()`：严格要求 `status` / `agent` / `task_id`，因为 dict 通常代表外部/runtime boundary。
- `from_any()`：可以通过 `agent` / `task_id` 参数补齐 dict 后再进入严格校验。

这是最近回归修复的重要 contract，不能随意删除。

## 14.7 结果比较必须保持业务语义

Task lifecycle 测试曾要求传入 result 与 Task 中保存的 result 完全一致，因此 TaskManager 不应在保存时无条件添加额外 `data: {}` 等字段破坏旧语义。

---

# 15. 关键功能 Commit 索引

| 状态 | 阶段 | Commit | Message |
|---|---|---|---|
| <span style="color:green">√</span> | Developer/Sandbox | `f9c42858fa3523b000428ff53bc6126bdd88ecac` | feat: establish developer agent with workspace sandbox |
| <span style="color:green">√</span> | Developer/Sandbox | `60ac4e8cea7986735e0d44fdb55e1cf9a92ea1a7` | feat: establish developer agent with workspace sandbox |
| <span style="color:green">√</span> | Task/Workflow | `75fcfe77746302d8f623e60052acd4b9adaddf78` | fix: keep task state transitions inside TaskManager |
| <span style="color:green">√</span> | Workflow | `dfb21a515c3f6896530f167bcf49332d63657b34` | fix: centralize workflow execution and robust failure handling |
| <span style="color:green">√</span> | Review History | `f8d8e2f24913f85c24cd7793bdc4febaaeac755c` | feat: add structured review history to task model |
| <span style="color:green">√</span> | Workflow Factory | `529ca53c004fb30569e935e58a6419461f7167a0` | feat: add centralized task workflow factory |
| <span style="color:green">√</span> | Dependency Graph | `4584078663bd8dc8b056a8d7599dc950ffc338b0` | feat: reject cyclic task dependencies |
| <span style="color:green">√</span> | Tester | `7b1e78b06e45280ce2ad4c8b5a4049f044b01936` | feat: add dedicated tester agent |
| <span style="color:green">√</span> | Tester Registry | `458f80504da4b4f116249e776593013619cf2cc7` | feat: register tester agent |
| <span style="color:green">√</span> | Quality Gate | `9ce87012603ac851f13611dc63416df2f9faf825` | fix: enforce developer tester reviewer quality gate |
| <span style="color:green">√</span> | Tester Recovery | `63eea6c37c995b167e1fd3431b10c01c9555bae7` | fix: restore tester workflow execution |
| <span style="color:green">√</span> | Workflow Result | `0d57e82c5c9942ceeeae552af10dc7f75d21423c` | refactor: simplify workflow result handling |
| <span style="color:green">√</span> | Context Compatibility | `ffad04127062dab03bb192e3cf0dbfa46092baa7` | fix: preserve legacy task context API |
| <span style="color:green">√</span> | Context Integration | `5a860447d95fb87da5d56c4f7efbf50e11e95f15` | add context flow integration tests |
| <span style="color:green">√</span> | Project Execution | `e2d31f3fc0e5e9873893dd69f786994411b03b35` | fix project execution test orchestrator |
| <span style="color:green">√</span> | Agent Factory | `79413eb445c1951d6d33948c23df09e11551ecb8` | fix agent factory custom configuration validation |
| <span style="color:green">√</span> | AgentResult | `3d9f2e3599774b4ca4e9184107f6419ccc4176ee` | feat: canonicalize agent results |
| <span style="color:green">√</span> | AgentResult compatibility | `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` | update code |
| <span style="color:green">√</span> | AgentResult Contract | `7bb371be68a9b2c9c9c94026efd06928b8e6817f` | fix: complete AgentResult compatibility contract |

---

# 16. 当前开发历史索引

以下近期 commit 已纳入原 DevPlan 历史记录；其中普通 `update code` 作为历史保留，架构里程碑以第 15 节为准。

```text
7bb371b  fix: complete AgentResult compatibility contract
31cc007  update code
5373c60  update code
2e278e5  update code
2327768  update code
569747d  update code
d61cf67  update code
49666ac  update code
7dcef21  update code
1c1d4f2  add runtime contract definitions
6528bf2  update code
906c365  update code
5a86044  add context flow integration tests
e2d31f3  fix project execution test orchestrator
bc417bb  update code
```

原 `docs/devplan` 分支还记录了更早的完整历史索引；本次同步没有改变其历史语义，新增的当前分支里程碑为 `7bb371b`。

---

# 17. 后续开发执行规则

以后每一个开发阶段必须遵守：

## Step A — 明确目标

在 DevPlan.md 中确定：

- 当前 Phase
- 当前 Feature
- 输入/输出 contract
- 不允许破坏的旧行为
- 验收标准

## Step B — 先测试

至少覆盖：

- happy path
- invalid input
- failure path
- regression case
- backward compatibility case（涉及旧 API 时）

## Step C — 最小修改

优先：

```text
新增能力
↓
兼容旧 API
↓
迁移调用方
↓
删除 legacy code
```

不要反过来。

## Step D — 完整回归

```powershell
pytest -q
```

必须全部通过。

## Step E — Commit

commit message 使用：

```text
feat: ...
fix: ...
refactor: ...
test: ...
docs: ...
```

## Step F — 更新 DevPlan.md

每次完成后同步记录：

- 绿色 `<span style="color:green">√</span>`
- commit SHA
- 变更说明
- 测试数量
- 遇到的问题
- 修复原因
- 下一步

---

# 18. 当前唯一下一步执行目标

## ☐ Phase 2.8 — Developer Result 完整结构化

不要立即进入 Phase 3。

首先完成：

1. 定义 Developer AgentResult `data` schema。
2. 明确 `message` 与 `data` 的职责边界。
3. 设计 `files_changed`、`tests`、`summary/report` 等字段。
4. 增加 DeveloperResult contract tests。
5. 修改 Developer `run()`，只返回合法、可序列化的结构化 AgentResult。
6. 确认 Workflow / TaskManager / ContextBuilder 不再依赖 SDK message object。
7. 执行完整 `pytest -q`。
8. 测试通过后提交 feature commit。
9. 再次更新 DevPlan.md。

**完成 Phase 2.8 后，才能进入 Phase 3 AgentContext 正式化。**

---

# 19. 开发历史原则

本文件是 AI-Team 的长期开发状态账本。

任何后续开发者或 AI Agent 修改项目之前，都应该先阅读：

1. 当前状态
2. 当前 Phase
3. 已完成功能
4. 关键 Commit
5. 问题与经验
6. 当前唯一下一步目标

不得因为某个测试再次失败，就从头重新设计 TaskManager / Workflow / AgentResult；应先通过测试和 commit 历史定位问题是否已经解决过。

最终开发闭环：

```text
需求
 ↓
DevPlan
 ↓
测试
 ↓
实现
 ↓
回归
 ↓
Commit
 ↓
DevPlan 更新
 ↓
下一阶段
```

目标是让 AI-Team 持续演进，而不是在同一个功能点反复重构、反复引入相同类型的 bug。
