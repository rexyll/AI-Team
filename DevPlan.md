# AI-Team 开发计划与开发历史

> **项目：** `rexyll/AI-Team`
>
> **文档目的：** 记录 AI-Team 从早期原型到当前 Runtime/Workflow/Agent 架构的完整演进路线、已完成能力、关键问题与修复、每个阶段对应的 Git commit，以及后续开发计划。
>
> **维护规则：** 每完成一个独立功能或架构阶段，必须同步更新本文件，并记录对应 commit SHA；出现回归问题时，先查本文件中的“问题与经验”及相关 commit，再继续修改代码，避免重复踩坑。

---

## 1. 当前项目状态

### 1.1 当前阶段

**当前处于：Phase 2 — Agent Contract / AgentResult 统一化阶段。**

Phase 1 的核心 Task Lifecycle、Developer → Tester → Reviewer 质量门禁、Review Loop、Task Context、Project Execution 等能力已经基本建立并持续修复。

当前重点不是继续扩展 Task 状态，而是把 Architect / Developer / Tester / Reviewer 的输出正式统一到 `AgentResult` contract，并进一步完成 Context、LLM、Tool/Sandbox 和最终 Project Orchestrator 的架构收敛。

### 1.2 当前验证状态

用户在本地 Windows 11 / Python `.venv` 环境执行：

```text
pytest -q

299 passed in 18.85s
```

因此，**当前本地基线为 299 个测试全部通过**。

> 注意：该数字来自本地工作区验证，不等同于 GitHub Actions 状态。GitHub 当前没有配置可用于这些 commit 的综合 CI 状态结果，因此后续每个阶段仍应在本地执行完整测试。

### 1.3 当前 Git 基线

GitHub `main` 当前最新已知 commit：

- `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` — `update code`

该 commit 继续完善 `AgentResult` legacy payload 归一化、`TaskManager` 对 `AgentResult` 的兼容，以及 workflow result 序列化。

---

# 2. 总体开发目标

AI-Team 的最终目标不是简单地让几个 Agent 顺序调用，而是构建一个**可测试、可恢复、可扩展、可替换 LLM、具备安全工具执行能力的 AI 软件开发团队 Runtime**。

目标架构：

```text
User Request
     │
     ▼
   Planner
     │
     ▼
 Project Plan
     │
     ▼
Dependency Graph
     │
     ├───────────────┐
     ▼               ▼
 Architect       Architect
     │               │
     └───────┬───────┘
             ▼
         Developer
             │
             ▼
           Tester
             │
       ┌─────┴─────┐
       │           │
    PASSED       FAILED
       │           │
       ▼           ▼
   Reviewer    Developer
       │
   ┌───┴────────┐
   │            │
APPROVED     REVISION
   │            │
   ▼            ▼
Complete      Developer
```

最终形成：

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
AgentResult / AgentContext
    ↓
ProjectResult
```

---

# 3. 已完成开发阶段

## Phase 0 — 基础项目骨架与 Agent 原型

### √ 0.1 建立多 Agent 基础结构

已建立 `agents/` 与 `runtime/` 基础目录，形成 Planner / Architect / Developer / Tester / Reviewer 等 Agent 角色，以及 Runtime 层的 Task / Workflow / Router / Factory 等基础模块。

### √ 0.2 Developer Agent + Workspace Sandbox

Developer Agent 已具备受保护工作区操作能力，并通过工具注册表执行文件读取、文件修改、测试/构建等操作。

关键原则：

- Agent 只能操作受保护工作区。
- 文件查看优先使用文件工具。
- `run_command` 主要用于测试、构建和专用开发工具。
- 修改代码前必须读取相关文件。
- Developer 工具循环必须有最大迭代次数，避免无限循环。

关键 commit：

- `f9c42858fa3523b000428ff53bc6126bdd88ecac` — `feat: establish developer agent with workspace sandbox`
- `60ac4e8cea7986735e0d44fdb55e1cf9a92ea1a7` — `feat: establish developer agent with workspace sandbox`
- `c9b02371389440926e667a73388ed837f5cace9f` — `fix: pass reviewer feedback into developer context and bound tool loop`
- `1e8255d471396b3a49ca1c7184d5e9b35c4f1709` — `fix: correct terminal command policy pattern`

### √ 0.3 Task Manager / Workflow 基础能力

TaskManager 逐渐成为 Task 状态变更的唯一入口，Workflow 负责 orchestration，而不是直接散落修改 Task 状态。

关键 commit：

- `75fcfe77746302d8f623e60052acd4b9adaddf78` — `fix: keep task state transitions inside TaskManager`
- `dfb21a515c3f6896530f167bcf49332d63657b34` — `fix: centralize workflow execution and robust failure handling`
- `7592dbeece2d14f9fea9a7bd21dbe568401dc2f2` — `refactor: route developer tasks through TaskWorkflow`
- `43108ad45f271f117a298b90d8414c56b313061d` — `refactor: centralize workflow state transitions and review history`

---

# 4. Phase 1 — Task Lifecycle / Quality Gate / Workflow 稳定化

## √ 1.1 Task 生命周期

核心状态已经建立并经过大量生命周期测试：

```text
pending
  ↓
ready
  ↓
running
  ↓
reviewing
  ↓
review_pending
  ↓
completed
```

失败和返工路径包括：

```text
Developer
   ↓
Tester FAILED
   ↓
Developer revision
   ↓
Tester
```

以及：

```text
Developer
   ↓
Tester PASSED
   ↓
Reviewer REVISION
   ↓
Developer revision
   ↓
Tester
   ↓
Reviewer
```

### √ 1.2 Tester Quality Gate

已经明确禁止 Reviewer 在 Tester 未通过时执行：

```text
Developer
   ↓
Tester
   ├── failed → Developer
   └── passed → Reviewer
```

关键 commit：

- `7b1e78b06e45280ce2ad4c8b5a4049f044b01936` — `feat: add dedicated tester agent`
- `458f80504da4b4f116249e776593013619cf2cc7` — `feat: register tester agent`
- `9ce87012603ac851f13611dc63416df2f9faf825` — `fix: enforce developer tester reviewer quality gate`
- `63eea6c37c995b167e1fd3431b10c01c9555bae7` — `fix: restore tester workflow execution`

`9ce870...` 明确规定 Reviewer 只有在 Tester 显式返回 `passed` 时才能运行；Tester `failed` 是可恢复的 Developer revision，而异常/非法结果属于终止失败。 

### √ 1.3 Reviewer Revision Loop

Reviewer 支持：

```text
APPROVED
REVISION_REQUIRED
```

并受 `max_review_rounds` 限制，避免无限审核循环。

关键 commit：

- `f8d8e2f24913f85c24cd7793bdc4febaaeac755c` — `feat: add structured review history to task model`
- `0d57e82c5c9942ceeeae552af10dc7f75d21423c` — `refactor: simplify workflow result handling`

### √ 1.4 Tester / Reviewer History

Task 已支持当前结果与历史结果分离：

- `test_result`
- `test_history`
- `review_result`
- `review_history`

并针对重复记录、同一结果再次出现、revision round 等情况建立测试。

### √ 1.5 Workflow Result Handling 收敛

将 Tester / Reviewer 的结果处理从主流程中抽离为独立 handler，减少主循环中的状态分支。

关键 commit：

- `0d57e82c5c9942ceeeae552af10dc7f75d21423c` — `refactor: simplify workflow result handling`

> 经验：此阶段曾出现“简化 Workflow 后 Tester 执行链路被绕过”的回归问题，之后通过 `63eea6...` 恢复 Tester 执行。因此以后任何 Workflow 重构必须优先保证 Developer → Tester → Reviewer 链路的集成测试。

---

# 5. Phase 1.5 — Dependency / Context Architecture

## √ 1.6 Task Dependency Graph

已经支持 Task dependencies，并拒绝循环依赖。

关键 commit：

- `4584078663bd8dc8b056a8d7599dc950ffc338b0` — `feat: reject cyclic task dependencies`

## √ 1.7 ContextBuilder

已经建立 `runtime/context_builder.py`，职责包括：

- 提供已完成依赖任务的结果
- 提供 Tester feedback
- 提供 Reviewer feedback
- 不修改 Task
- 不改变 Task status
- 不执行 Agent
- 不负责 Workflow transition

关键 commit：

- `ffad04127062dab03bb192e3cf0dbfa46092baa7` — `fix: preserve legacy task context API`
- `5a860447d95fb87da5d56c4f7efbf50e11e95f15` — `add context flow integration tests`

`5a860...` 增加了完整的 Context Flow 集成测试，验证依赖结果可以从 Workflow 传递到 Developer、Tester、Reviewer，并验证 snapshot 不会反向修改 Task。

## √ 1.8 Reviewer Feedback → Developer Context

Reviewer revision 后的反馈已经能够重新进入 Developer 的上下文，使 Developer 下一轮可以根据审核意见继续修改。

关键 commit：

- `c9b02371389440926e667a73388ed837f5cace9f`

---

# 6. Phase 1.6 — Project Planning / Orchestration

## √ 1.9 Planner / PlanBuilder / Project Execution

已经形成从 Project Plan 到 Task 列表再到执行的基础链路，并补充 Project Execution 测试。

关键 commit：

- `e2d31f3fc0e5e9873893dd69f786994411b03b35` — `fix project execution test orchestrator`

该修复明确要求测试计划包含：

- project
- summary
- task dependencies

并修复测试 orchestrator 对 Task 状态的执行假设。

## √ 1.10 Agent Factory / Registry / Configuration

已经存在：

- `runtime/agent_factory.py`
- `runtime/agent_registry.py`
- `runtime/agent_config.py`

并处理 custom configuration validation。

关键 commit：

- `529ca53c004fb30569e935e58a6419461f7167a0` — `feat: add centralized task workflow factory`
- `79413eb445c1951d6d33948c23df09e11551ecb8` — `fix agent factory custom configuration validation`

---

# 7. Phase 2 — AgentResult Contract 统一化

## √ 2.1 建立 AgentResult

已经建立统一结果模型：

```python
AgentResult(
    status,
    agent,
    task_id,
    message,
    data,
)
```

目标是让所有 Agent 最终统一返回同一种结果，而不是 Architect / Developer / Tester / Reviewer 各自返回不同 dictionary。

关键 commit：

- `3d9f2e3599774b4ca4e9184107f6419ccc4176ee` — `feat: canonicalize agent results`

该阶段增加了：

- canonical status
- legacy status mapping
- canonical `data`
- legacy payload normalization
- `to_dict()`
- dictionary-style access
- `from_dict()`

## √ 2.2 Legacy Status Compatibility

历史状态已经统一映射：

```text
architect_completed → completed
developer_completed → completed
tester_passed       → passed
tester_failed       → failed
reviewer_approved   → approved
reviewer_revision   → revision
```

## √ 2.3 Legacy Payload → data

旧 Agent 结果：

```python
{
    "status": "completed",
    "agent": "developer",
    "task_id": "TASK-002",
    "result": {
        "implementation": "..."
    }
}
```

会归一化成：

```python
AgentResult(
    status="completed",
    agent="developer",
    task_id="TASK-002",
    data={
        "implementation": "..."
    },
)
```

最新相关 commit：

- `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` — `update code`

该 commit 继续完善 `result` → `data` 的 legacy payload 兼容，并使 TaskManager 可以接受支持 `to_dict()` 的 AgentResult。

## √ 2.4 Runtime Result Normalizer

已经建立：

```text
runtime/result_normalizer.py
```

统一负责把：

```text
AgentResult
dict
```

转换成 AgentResult。

---

# 8. 当前 Phase 2 尚未完全完成的部分

## ☐ 2.5 所有 Agent 正式返回 AgentResult

当前仍存在 legacy Agent 返回 dictionary 的情况，尤其 Architect 仍存在类似：

```python
return {
    "status": "architect_completed",
    "agent": self.role,
    "task_id": task.id,
    "architecture": result,
}
```

**目标：** 所有 Agent 的 `run()` 都严格返回 `AgentResult`。

范围：

- `agents/base.py`
- `agents/architect.py`
- `agents/developer.py`
- `agents/tester.py`
- `agents/reviewer.py`
- mock agents
- 相关测试

## ☐ 2.6 BaseAgent 类型契约

最终目标：

```python
def run(self, task: Task) -> AgentResult:
    ...
```

所有具体 Agent 必须遵守该契约。

## ☐ 2.7 AgentResult 辅助 API 完整化

计划支持：

```python
AgentResult.from_any(...)
result.succeeded
result.failed
result.requires_revision
```

注意：这些方法必须定义在 `AgentResult` 类内部，不能因为缩进错误而落到类外成为普通函数/属性。

## ☐ 2.8 Developer Result 结构化

Developer 当前仍需要进一步区分：

```text
message = 人类可读总结

data   = 结构化开发结果
```

例如：

```python
AgentResult(
    status="completed",
    agent="developer",
    task_id=task.id,
    message="Implementation completed successfully.",
    data={
        "report": "...",
    },
)
```

不能把 LLM SDK 的 message object 直接放进 `message: str`。

---

# 9. Phase 3 — AgentContext 正式化

## ☐ 3.1 Task → AgentContext

目标架构：

```text
Task
 ↓
ContextBuilder
 ↓
AgentContext
 ↓
Agent
```

AgentContext 已经存在，字段包括：

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

下一阶段要做的是让 Agent 真正消费这个稳定的 read-only context，而不是直接依赖 Task 内部结构。

## ☐ 3.2 Context Snapshot 完整化

必须继续保持：

- Agent 不能修改原 Task
- dependency context 为 snapshot
- 不允许把未完成 dependency 暴露给下游 Agent
- Tester / Reviewer 只获得执行时需要的信息

## ☐ 3.3 Context History

将 Task execution history、test history、review history 以统一格式暴露给 Agent，避免不同 Agent 自己拼接历史。

---

# 10. Phase 4 — LLM Abstraction

当前项目已经存在：

```text
runtime/llm/base.py
runtime/llm/mock.py
```

但部分 Agent 仍直接依赖：

```python
from config.model import ask_ai
```

或 Developer 直接使用：

```python
client.chat.completions.create(...)
```

## ☐ 4.1 BaseLLM 完整实现

目标：

```python
class BaseLLM(ABC):
    def generate(...):
        ...
```

## ☐ 4.2 MockLLM

实现完全离线的 Mock LLM，使 Agent 测试不依赖真实模型。

## ☐ 4.3 Provider Adapter

把 OpenAI-compatible / 其他模型提供商封装到 LLM Adapter 中。

最终 Agent 不应直接知道 SDK：

```text
Agent
 ↓
BaseLLM
 ↓
Provider Adapter
 ↓
LLM API
```

## ☐ 4.4 Prompt / Model / Temperature 配置化

统一由 AgentConfig / Runtime Configuration 控制：

- model
- system prompt
- temperature
- max tokens
- timeout
- retry

---

# 11. Phase 5 — Tool / Sandbox Architecture

当前 Developer 已具备工具调用能力，并有 `security.tool_guard`。

下一阶段将工具体系从“Developer 内部逻辑”抽象成 Runtime 能力：

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

## ☐ 5.1 ToolExecutor

统一执行所有 Agent Tool Call。

## ☐ 5.2 Tool Policy

按 Agent Role 控制权限：

```text
Architect → read-only / no command
Developer → read/write + test/build
Tester    → read/test
Reviewer  → read-only
Planner   → planning tools
```

## ☐ 5.3 Workspace Sandbox

继续强化：

- 工作区边界
- 路径规范化
- 禁止目录逃逸
- 命令白名单/黑名单
- 工具参数校验
- 错误隔离

## ☐ 5.4 Tool Loop Reliability

保持最大 tool iterations，并增加：

- timeout
- repeated-call detection
- invalid argument handling
- tool result size limit
- cancellation

---

# 12. Phase 6 — Project Orchestrator

## ☐ 6.1 Project Execution State

Project 级状态：

```text
created
 ↓
planning
 ↓
planned
 ↓
executing
 ↓
completed / failed / blocked
```

## ☐ 6.2 Dependency-aware Scheduling

只有依赖全部完成的 Task 才进入 ready。

## ☐ 6.3 并行执行

未来支持无依赖 Task 并行：

```text
TASK-001 ──┐
           ├── TASK-003
TASK-002 ──┘
```

## ☐ 6.4 Failure Recovery

区分：

- Agent business failure
- Tester failure
- Reviewer revision
- Tool failure
- LLM failure
- Runtime exception
- Dependency failure

## ☐ 6.5 ProjectResult

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

# 13. Phase 7 — Persistence / Observability

## ☐ 7.1 Execution Persistence

保存：

- project
- plan
- task
- task state history
- AgentResult
- AgentContext snapshot
- tool calls
- errors

## ☐ 7.2 Event Log

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

## ☐ 7.3 Structured Logging

所有 Runtime 日志统一字段：

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

# 14. Phase 8 — Production Hardening

## ☐ 8.1 Retry / Timeout

LLM、Tool、Agent 都需要统一 timeout/retry policy。

## ☐ 8.2 Cancellation

支持用户主动取消 Project / Task。

## ☐ 8.3 Concurrency Control

限制：

- Agent concurrency
- Tool concurrency
- LLM concurrency
- Project concurrency

## ☐ 8.4 Security Audit

重点检查：

- path traversal
- command injection
- prompt injection
- secret leakage
- tool privilege escalation
- workspace escape

## ☐ 8.5 Full Regression Suite

目标：

```text
pytest -q
```

必须全部通过，并将测试数量记录到本文件。

---

# 15. 开发过程中已经出现过的重要问题与经验

## 15.1 不要让 Workflow 直接修改 Task 状态

问题：状态修改散落在 Workflow 中会导致状态不一致。

解决：集中到 TaskManager。

commit：

`75fcfe77746302d8f623e60052acd4b9adaddf78`

结论：

> **TaskManager 管状态，Workflow 管流程，Agent 管执行。**

---

## 15.2 Tester 必须是 Reviewer 前的质量门禁

曾经出现 Workflow 简化后 Tester 执行路径被绕过的问题。

修复：

- `63eea6c37c995b167e1fd3431b10c01c9555bae7`
- `9ce87012603ac851f13611dc63416df2f9faf825`

结论：

> Reviewer 不能替代 Tester；Tester failed 必须回到 Developer，而不是直接进入 Reviewer。

---

## 15.3 Legacy API 不要无条件删除

ContextBuilder 重构时保留了：

```python
build_task_context(task, all_tasks)
```

旧 API，但让它返回旧格式；新代码使用：

```python
ContextBuilder(all_tasks).build(task)
```

commit：

`ffad04127062dab03bb192e3cf0dbfa46092baa7`

结论：

> 新架构可以向前推进，但兼容边界必须明确，并由测试保护。

---

## 15.4 AgentResult 必须兼容历史 Agent

旧 Agent 有：

```text
architect_completed
developer_completed
tester_passed
tester_failed
reviewer_approved
reviewer_revision
```

统一后不能一次性破坏所有历史测试和 Workflow。

解决：

`LEGACY_STATUS_MAPPING` + legacy payload normalization。

commit：

`3d9f2e3599774b4ca4e9184107f6419ccc4176ee`

以及：

`6528bf27e4a820c1eea2f0a98d1030e4c47f6599`

结论：

> **先建立 canonical contract，再逐步迁移生产 Agent；不要先删除兼容层。**

---

## 15.5 同一结果是否重复记录必须有明确语义

Tester history 与 Reviewer history 对重复结果的处理必须由测试定义，而不是凭感觉修改。

当前测试已经覆盖：

- 当前结果更新
- history 保留
- revision
- 相同结果再次出现仍可代表新的 round
- Tester revision 不应产生重复 history

结论：

> History 是执行事件历史，不应该简单用 dict equality 代替业务语义。

---

## 15.6 299 passed 是当前本地稳定基线

后续任何架构重构都必须遵守：

```text
修改前
  ↓
pytest -q
  ↓
确认基线
  ↓
新增/修改测试
  ↓
修改实现
  ↓
pytest -q
  ↓
全部通过
  ↓
提交 commit
  ↓
更新 DevPlan.md
```

禁止在没有测试保护的情况下大规模重构。

---

# 16. 关键功能 Commit 索引

下面记录已经识别出的具有明确功能/修复意义的 commit。普通的 `update code` 提交不作为独立架构里程碑，但仍保留在后面的完整历史索引中。

| 状态 | 阶段 | Commit | Message |
|---|---|---|---|
| <span style="color:green">√</span> | Developer/Sandbox | `f9c42858fa3523b000428ff53bc6126bdd88ecac` | feat: establish developer agent with workspace sandbox |
| <span style="color:green">√</span> | Developer/Sandbox | `60ac4e8cea7986735e0d44fdb55e1cf9a92ea1a7` | feat: establish developer agent with workspace sandbox |
| <span style="color:green">√</span> | Task/Agent/Workflow | `bdd52a0cd9337b5ca646eb3ea1f793d7d7b94af9` | fix bugs:task manager agent and workflow agent |
| <span style="color:green">√</span> | Review History | `f8d8e2f24913f85c24cd7793bdc4febaaeac755c` | feat: add structured review history to task model |
| <span style="color:green">√</span> | Workflow Factory | `529ca53c004fb30569e935e58a6419461f7167a0` | feat: add centralized task workflow factory |
| <span style="color:green">√</span> | Dependency Graph | `4584078663bd8dc8b056a8d7599dc950ffc338b0` | feat: reject cyclic task dependencies |
| <span style="color:green">√</span> | Tester | `7b1e78b06e45280ce2ad4c8b5a4049f044b01936` | feat: add dedicated tester agent |
| <span style="color:green">√</span> | Tester Registry | `458f80504da4b4f116249e776593013619cf2cc7` | feat: register tester agent |
| <span style="color:green">√</span> | Workflow State | `43108ad45f271f117a298b90d8414c56b313061d` | refactor: centralize workflow state transitions and review history |
| <span style="color:green">√</span> | Reviewer→Developer Context | `c9b02371389440926e667a73388ed837f5cace9f` | fix: pass reviewer feedback into developer context and bound tool loop |
| <span style="color:green">√</span> | TaskManager Ownership | `75fcfe77746302d8f623e60052acd4b9adaddf78` | fix: keep task state transitions inside TaskManager |
| <span style="color:green">√</span> | Workflow Error Handling | `dfb21a515c3f6896530f167bcf49332d63657b34` | fix: centralize workflow execution and robust failure handling |
| <span style="color:green">√</span> | Workflow Routing | `7592dbeece2d14f9fea9a7bd21dbe568401dc2f2` | refactor: route developer tasks through TaskWorkflow |
| <span style="color:green">√</span> | Command Policy | `1e8255d471396b3a49ca1c7184d5e9b35c4f1709` | fix: correct terminal command policy pattern |
| <span style="color:green">√</span> | Ready Task Execution | `bed365389dd42cd78bd8d13238541add80b56aee` | fix: orchestrator executes already-ready tasks |
| <span style="color:green">√</span> | Quality Gate | `9ce87012603ac851f13611dc63416df2f9faf825` | fix: enforce developer tester reviewer quality gate |
| <span style="color:green">√</span> | Tester Recovery | `63eea6c37c995b167e1fd3431b10c01c9555bae7` | fix: restore tester workflow execution |
| <span style="color:green">√</span> | Workflow Result Handling | `0d57e82c5c9942ceeeae552af10dc7f75d21423c` | refactor: simplify workflow result handling |
| <span style="color:green">√</span> | Context Compatibility | `ffad04127062dab03bb192e3cf0dbfa46092baa7` | fix: preserve legacy task context API |
| <span style="color:green">√</span> | AgentResult | `3d9f2e3599774b4ca4e9184107f6419ccc4176ee` | feat: canonicalize agent results |
| <span style="color:green">√</span> | Context Integration | `5a860447d95fb87da5d56c4f7efbf50e11e95f15` | add context flow integration tests |
| <span style="color:green">√</span> | Agent Factory | `79413eb445c1951d6d33948c23df09e11551ecb8` | fix agent factory custom configuration validation |
| <span style="color:green">√</span> | Project Execution | `e2d31f3fc0e5e9873893dd69f786994411b03b35` | fix project execution test orchestrator |
| <span style="color:green">√</span> | AgentResult Legacy Payload | `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` | update code — normalize legacy result payload into data |

---

# 17. 完整 Git 历史索引（当前已检索到的提交）

> GitHub API 当前已检索到的近期提交如下。对于没有明确功能语义的 `update code`，它们作为历史记录保留；真正的阶段完成以第 16 节的功能 commit 为准。

| 时间 | Commit | Message |
|---|---|---|
| 2026-08-20 | `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` | update code |
| 2026-08-20 | `906c3651b7a04932d6820e1d55c68780f4c82d6f` | update code |
| 2026-08-20 | `5a860447d95fb87da5d56c4f7efbf50e11e95f15` | add context flow integration tests |
| 2026-08-20 | `e2d31f3fc0e5e9873893dd69f786994411b03b35` | fix project execution test orchestrator |
| 2026-08-20 | `bc417bb86a31a603fe268a3aa615961f47eca875` | update code |
| 2026-08-20 | `e4176c822ebf564940ebd518d805744a2fe1b8cc` | update code |
| 2026-08-20 | `353ef452c798190de24b0aa72c957843460f86ed` | update code |
| 2026-08-20 | `79413eb445c1951d6d33948c23df09e11551ecb8` | fix agent factory custom configuration validation |
| 2026-08-20 | `e9502e0aa6953cd846dd44c2c009050f1e6d8fec` | update code |
| 2026-08-20 | `f28ad635dca8a9a1a146c33887846c489c33c6cb` | update code |
| 2026-08-20 | `39feecbc829b904f3a09275abbe50bbd210ff242` | update code |
| 2026-08-20 | `4139326971de63024cbc84b54e44e4a5092196f7` | update code |
| 2026-08-20 | `7533def80296263476c49c2b19fbd8397713ee5c` | update code |
| 2026-08-20 | `4e070244dbcf2adb8dea4e07967822a8838ed30b` | update code |
| 2026-08-20 | `0ae613ea57f545168b7a1e3dc862123139d475f5` | update code |
| 2026-08-20 | `2604b39b7081b027f53f3c4ce8759b1c8cec70b3` | update code |
| 2026-08-19 | `f9202b38c042259bfbf7c0fd49ace9e661652a5e` | update code |
| 2026-08-19 | `4e97765605361b3875840b0f4e8dc92e3bcef427` | update code |
| 2026-08-19 | `852944d9e5ff4e9a2d03893ba09a8ee5d254abca` | update code |
| 2026-08-19 | `76659321cc739684f7dc8b1bd5c91f81589aef71` | update code |
| 2026-08-19 | `0b340046a86e3844e494ce8dd2b1f3b10f3dd049` | update code |
| 2026-08-19 | `38d07d3e0b8b7a7700c73c9c57d681d04637a31a` | update code |
| 2026-08-19 | `714ee097a36db673a12f3a20b1b1c2730be6f03e` | update code |
| 2026-08-19 | `726fe047a3e7b9ef17a796df4d5154c402700519` | update code |
| 2026-08-19 | `4209dfb827939d169b12b6e335384967433d892c` | update code |
| 2026-08-19 | `92bbb8703fcca1a3eafd2773868410a430f77e7d` | update code |
| 2026-08-19 | `48a5a00b05bb75066aa7a1404c6d6d13ae8afaa5` | update code |
| 2026-08-19 | `4122ab5a83f3d221cdd247c0ec306e4b5b146d6d` | update code |
| 2026-08-19 | `3d9f2e3599774b4ca4e9184107f6419ccc4176ee` | feat: canonicalize agent results |
| 2026-08-19 | `ffad04127062dab03bb192e3cf0dbfa46092baa7` | fix: preserve legacy task context API |
| 2026-08-19 | `96d070d372707e8a48649cbf8e93524062a7b58a` | update code |
| 2026-08-19 | `9feb323c30feddbbb144cb22955de351ad4f0bab` | update code |
| 2026-08-19 | `19652c72434565b05fd99548fa610d2399a44f10` | update code |
| 2026-08-19 | `7bd8ea3b9791bc8e86da88720c0611078dd85b4f` | update code |
| 2026-08-19 | `63eea6c37c995b167e1fd3431b10c01c9555bae7` | fix: restore tester workflow execution |
| 2026-08-19 | `4f2a5c1a60418f28254777033639409f830569d7` | update code |
| 2026-08-19 | `0d57e82c5c9942ceeeae552af10dc7f75d21423c` | refactor: simplify workflow result handling |
| 2026-08-19 | `1f599531cdfda71895d9bc684f09879327e3495a` | update code |
| 2026-08-19 | `03eeadab2c79a128865078053fd2edc30854af60` | update code |
| 2026-08-19 | `0d6929aed9553ad3a974392a4d18fa36b4bb48f9` | update code |
| 2026-08-19 | `af5957ed67365dbff130608910b9e3dfcff073e6` | update code |
| 2026-08-19 | `1fc141d356e10d9479e8516b6b15e96d092087a9` | update code |
| 2026-08-19 | `4abd7ab43ebb4e5585735948f3a57138fabd71db` | update code |
| 2026-08-19 | `6eb02e37ad981bc155d589561f59829e19ffa8b4` | update code |
| 2026-08-19 | `3b4a6a7cc44dd07bc4991d641faea17da5fb78fa` | update code |
| 2026-08-18 | `6bac6b229a3539a994b00d61face46a22c333fc8` | update code |
| 2026-08-18 | `1a54dfab6aeb2ae87e123f5708d19e24b5587a1a` | update code |
| 2026-08-18 | `9ce87012603ac851f13611dc63416df2f9faf825` | fix: enforce developer tester reviewer quality gate |
| 2026-08-18 | `a61881bbcb9b8b00cd7b28c470a1b38cd5da3258` | update code |
| 2026-08-18 | `6369ea76b634455a7701780b7a6de18c3fd8bfb4` | update code |

---

# 18. 后续开发执行规则

以后每一个开发阶段都必须遵守以下流程：

## Step A — 明确目标

先在 DevPlan.md 中确定：

- 当前 Phase
- 当前 Feature
- 输入/输出 contract
- 不允许破坏的旧行为
- 验收标准

## Step B — 先写测试

至少增加：

- happy path
- invalid input
- failure path
- regression case
- backward compatibility case（如果涉及旧 API）

## Step C — 修改最小范围

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

commit message 必须说明功能：

```text
feat: ...
fix: ...
refactor: ...
test: ...
docs: ...
```

## Step F — 更新 DevPlan.md

把：

- 功能状态改为 `<span style="color:green">√</span>`
- commit SHA
- 变更说明
- 测试数量
- 遇到的问题
- 修复原因
- 下一步

同步写入。

---

# 19. 当前下一步唯一执行目标

**Phase 2.5 — 完成 AgentResult Contract 的正式迁移。**

执行顺序：

1. ☐ 修正 `runtime/agent_result.py` 类内方法缩进与完整 API
2. ☐ 增加/完善 AgentResult 单元测试
3. ☐ 修改 `agents/base.py`，规定 `run() -> AgentResult`
4. ☐ 修改 Architect 返回 AgentResult
5. ☐ 修改 Developer 返回严格合法的 AgentResult
6. ☐ 修改 Tester 返回结构化 AgentResult
7. ☐ 修改 Reviewer 返回结构化 AgentResult
8. ☐ 修改 Mock Agents
9. ☐ 删除/减少 Workflow 对 legacy dictionary 的特殊判断
10. ☐ 保留 `result_normalizer.py` 作为迁移期兼容边界
11. ☐ 执行 `pytest -q`
12. ☐ 保持所有现有测试通过
13. ☐ 提交 feature commit
14. ☐ 把该 commit 写入 DevPlan.md

**完成 Phase 2.5 后才能进入 Phase 3 AgentContext 正式化。**

---

# 20. 开发历史原则

本文件从现在开始作为 AI-Team 的**开发状态账本（Development Ledger）**。

任何后续开发者或 AI Agent 在修改项目之前，都应该先阅读：

1. 当前状态
2. 当前 Phase
3. 已完成功能
4. 关键 Commit
5. 问题与经验
6. 当前唯一下一步目标

不得因为某个测试再次失败，就从头重新设计 TaskManager / Workflow / AgentResult；应先通过 commit 和测试历史定位该问题是否已经解决过。

最终目标是让 AI-Team 的开发过程形成：

```text
需求
 ↓
开发计划
 ↓
测试
 ↓
实现
 ↓
回归
 ↓
Commit
 ↓
DevPlan.md
 ↓
下一阶段
```

从而避免重复修改、重复引入同一类 bug，并保证项目架构能够持续演进而不是反复重构。
