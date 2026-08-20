# AI-Team 开发计划与开发历史

> 项目：`rexyll/AI-Team`  
> 当前分支：`refactor/runtime-architecture`  
> 本文件是 Development Ledger：已完成节点使用绿色 `√`；进行中节点使用 `☐`。每个迁移节点严格遵循：GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Push → 记录最终 SHA → DevPlan √ → 下一节点。

---

# 1. 当前状态

## 1.1 最新稳定基线

用户本地最新全量验证：

```text
pytest -q
373 passed in 31.93s
```

**当前基线：373 passed / 0 failed。**

最新远程 HEAD：

- `483be86` — `test: cover AgentContext dependency snapshots`
- `39102e5` — `fix: preserve AgentContext serialization compatibility`
- `4a848c7` — `test: add DeveloperAgent AgentContext contract coverage`

## 1.2 当前阶段

**Phase 3 — AgentContext 正式化。**

Phase 0/1 已建立 Task Lifecycle、Developer → Tester → Reviewer Quality Gate、Review Loop、Dependency、ContextBuilder、Project Execution；Phase 2 已完成 AgentResult 统一契约；Phase 3.1a / 3.1b / 3.1c 已完成。

**当前节点：Phase 3.1d — Tester / Reviewer → AgentContext 迁移。**

---

# 2. 总体架构目标

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
ContextBuilder
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

质量门禁保持：

```text
Developer → Tester FAILED → Developer revision → Tester
Developer → Tester PASSED → Reviewer
                         ├→ REVISION → Developer
                         └→ APPROVED → Complete
```

---

# 3. 已完成历史

## Phase 0 — 基础骨架

### <span style="color:green">√</span> 0.1 多 Agent 基础结构

已建立 Planner / Architect / Developer / Tester / Reviewer，以及 Task / Workflow / Router / Factory。

### <span style="color:green">√</span> 0.2 Developer + Workspace Sandbox

Developer 具备 Workspace Sandbox、Tool Registry、文件读写、测试/构建和 Tool Loop 上限。

关键 commits：

- `f9c42858` / `60ac4e8c` — establish developer agent with workspace sandbox
- `c9b02371` — pass reviewer feedback and bound tool loop
- `1e8255d4` — correct terminal command policy

### <span style="color:green">√</span> 0.3 TaskManager / Workflow

TaskManager 负责状态变更，Workflow 负责 orchestration。

- `75fcfe77` — keep task state transitions inside TaskManager
- `dfb21a51` — centralize workflow execution and failure handling
- `7592dbee` — route developer tasks through TaskWorkflow
- `43108ad4` — centralize workflow transitions and review history

## Phase 1 — Lifecycle / Quality Gate

### <span style="color:green">√</span> 1.1 Task Lifecycle

```text
pending → ready → running → reviewing → review_pending → completed
```

### <span style="color:green">√</span> 1.2 Tester Quality Gate

Reviewer 只有在 Tester `passed` 后才能运行；Tester `failed` 回到 Developer。

- `7b1e78b0` — dedicated tester agent
- `458f8050` — register tester agent
- `9ce87012` — enforce quality gate
- `63eea6c3` — restore tester workflow execution

### <span style="color:green">√</span> 1.3 Reviewer Revision Loop

支持 `APPROVED` / `REVISION_REQUIRED` 与 `max_review_rounds`。

- `f8d8e2f2` — structured review history
- `0d57e82c` — simplify workflow result handling

### <span style="color:green">√</span> 1.4 Tester / Reviewer History

支持 `test_result`、`test_history`、`review_result`、`review_history`。

### <span style="color:green">√</span> 1.5 Workflow Result Handling

Tester / Reviewer handling 从主流程抽离。

## Phase 1.5 — Dependency / Context

### <span style="color:green">√</span> 1.6 Dependency Graph

支持依赖并拒绝循环依赖。

- `45840786` — reject cyclic dependencies

### <span style="color:green">√</span> 1.7 ContextBuilder

提供 completed dependency result、Tester feedback、Reviewer feedback，并保持不修改 Task、不执行 Agent、不控制 Workflow。

- `ffad0412` — preserve legacy task context API
- `5a860447` — context flow integration tests

### <span style="color:green">√</span> 1.8 Reviewer Feedback → Developer Context

- `c9b02371`

## Phase 1.6 — Planning / Orchestration

### <span style="color:green">√</span> 1.9 Planner / PlanBuilder / Project Execution

- `e2d31f3f` — fix project execution test orchestrator

### <span style="color:green">√</span> 1.10 Agent Factory / Registry / Configuration

- `529ca53c` — centralized task workflow factory
- `79413eb4` — custom configuration validation

---

# 4. Phase 2 — AgentResult Contract

### <span style="color:green">√</span> 2.1 AgentResult

统一结构：

```python
AgentResult(status, agent, task_id, message, data)
```

- `3d9f2e35` — canonicalize agent results

### <span style="color:green">√</span> 2.2 Legacy Status / Payload Compatibility

统一 legacy status，并将旧 Agent-specific payload 归一化到 `data`，保持 dictionary-style access。

- `6528bf27` — AgentResult legacy compatibility
- `7bb371b` — complete AgentResult compatibility contract

### <span style="color:green">√</span> 2.3 Result Normalizer / Agent Contract

Architect / Developer / Tester / Reviewer 均返回 AgentResult；`run(Task) -> AgentResult` 成为统一契约。

### <span style="color:green">√</span> 2.4 Tester / Reviewer Result 标准化

- `5bc0575` — standardize tester and reviewer agent results

专项验证历史：

```text
pytest tests/test_developer_result.py -q   → 5 passed
pytest tests/test_agent_result.py -q       → 36 passed
pytest tests/test_task_lifecycle.py -q    → 23 passed
pytest tests/test_context_flow.py -q       → 10 passed
```

---

# 5. Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.1a BaseAgent → AgentContext

建立兼容桥：

```text
Task → BaseAgent.build_context() → AgentContext
```

完成：

- `BaseAgent.build_context()`
- Agent role 自动注入
- `all_tasks` 支持
- dependency snapshot
- Task / AgentContext 隔离
- BaseAgent context bridge contract tests

关键 commits：

- `0118003` — record Phase 3.1a and enter Architect migration
- `8d0745b` — BaseAgent context bridge contract tests
- `2786309` — `feat: add BaseAgent AgentContext compatibility bridge`

验收：

```text
pytest -q
362 passed in 21.11s
```

## <span style="color:green">√</span> 3.1b ArchitectAgent → AgentContext

Architect 保持：

```text
run(Task) -> AgentResult
```

内部改为：

```text
Task → build_context() → AgentContext → Prompt → AgentResult
```

最终验收 commit：

- `ae729f4` — `feat: migrate architect agent to AgentContext`

用户已 Push，远程与本地 HEAD 一致。

## <span style="color:green">√</span> 3.1c DeveloperAgent → AgentContext

Developer 完成迁移，同时解决了原有 AgentContext 无法完整承载 completed dependency result 的边界问题。

### 3.1c Context Contract

AgentContext 现在同时提供：

```text
 dependencies
     ↓
 ["TASK-001", ...]

 dependency_context
     ↓
 {
   "TASK-001": {
      "title": "...",
      "role": "architect",
      "result": {...}
   }
 }
```

这样 Developer 可以获得 Architect 的完整结果，同时仍保持 compact dependency-ID view。

### 3.1c 迁移原则

- 保持 `run(Task) -> AgentResult`
- Developer prompt 改为消费 AgentContext
- Tool Loop / Tool Registry / Tool Guard 不改变
- `changed_files` / tests / evidence 不改变
- Workflow / TaskManager / Quality Gate 不改变
- AgentContext 使用 deep-copy snapshot
- 保留序列化兼容性

### 3.1c 最终验收

用户 Push 后远程 HEAD：

- `483be86` — `test: cover AgentContext dependency snapshots`
- `39102e5` — `fix: preserve AgentContext serialization compatibility`
- `4a848c7` — `test: add DeveloperAgent AgentContext contract coverage`

**本节点最终验收 SHA：`483be86`。**

用户本地全量测试：

```text
pytest -q
373 passed in 31.93s
```

**Phase 3.1c 正式完成。**

---

## ☐ 3.1d Tester / Reviewer → AgentContext

### 目标

将 Tester / Reviewer 内部 prompt 构造从 Task 直接读取迁移为：

```text
Task
 ↓
BaseAgent.build_context()
 ↓
AgentContext
 ↓
Tester / Reviewer prompt
 ↓
AgentResult
```

### Tester 必须消费

```text
context.task_id
context.task_title
context.task_description
context.task_result
context.tester_feedback
context.reviewer_feedback
context.history
context.metadata
context.dependency_context
```

重点保持 Developer Result / test evidence 的语义。

### Reviewer 必须消费

```text
context.task_id
context.task_title
context.task_description
context.task_result
context.tester_feedback
context.reviewer_feedback
context.history
context.metadata
context.dependency_context
```

重点保持：

- Tester status
- Developer tests
- Developer files_changed
- Architect dependency result
- previous review result
- revision loop

### 3.1d 严格边界

只修改：

- `agents/tester.py`
- `agents/reviewer.py`
- 对应 AgentContext contract tests

不修改：

- Workflow
- TaskManager
- Task lifecycle
- Quality Gate
- DependencyGraph

外部接口继续保持：

```python
agent.run(task) -> AgentResult
```

---

# 6. Phase 3 后续

### ☐ 3.2 Context Snapshot 完整化

确认 Agent 不修改原 Task；dependency context 是 snapshot；未完成 dependency 不暴露；Tester / Reviewer 只获得执行所需信息。

### ☐ 3.3 Context History

统一暴露 lifecycle / test / review history。

---

# 7. 后续路线

## Phase 4 — LLM Abstraction

### ☐ 4.1 BaseLLM 完整实现
### ☐ 4.2 MockLLM
### ☐ 4.3 Agent → BaseLLM
### ☐ 4.4 Workflow → LLM-independent
### ☐ 4.5 Provider/config 可替换

## Phase 5 — Tool / Sandbox Architecture

### ☐ 5.1 Tool Contract
### ☐ 5.2 Tool Registry Contract
### ☐ 5.3 Tool Argument Validation
### ☐ 5.4 Workspace Sandbox
### ☐ 5.5 Tool Permission Policy
### ☐ 5.6 Tool Error Contract

## Phase 6 — Workflow / Project Orchestrator

### ☐ 6.1 TaskWorkflow 状态机
### ☐ 6.2 Dependency-aware Scheduler
### ☐ 6.3 ProjectOrchestrator
### ☐ 6.4 Task 并行执行
### ☐ 6.5 Retry / Resume
### ☐ 6.6 ProjectResult

## Phase 7 — Persistence / Observability

### ☐ 7.1 Task persistence
### ☐ 7.2 Project persistence
### ☐ 7.3 Agent execution records
### ☐ 7.4 Tool execution logs
### ☐ 7.5 Workflow event log
### ☐ 7.6 Resume from persisted state

## Phase 8 — Production Hardening

### ☐ 8.1 Contract Tests
### ☐ 8.2 Failure Injection Tests
### ☐ 8.3 Security Tests
### ☐ 8.4 LLM Mock Integration Tests
### ☐ 8.5 Long-running Workflow Tests
### ☐ 8.6 Performance / Concurrency Tests
### ☐ 8.7 Documentation / Examples

---

# 8. 重要问题与经验

1. **Workflow 不能绕过 Tester。** `63eea6c` 修复过该回归；Workflow 重构必须先跑 Developer → Tester → Reviewer 集成测试。
2. **AgentResult 必须兼容旧 API。** `7bb371b` 修复过默认字段、from_dict 校验和 legacy payload access。
3. **AgentContext 必须是 snapshot。** 使用 deep copy，避免 Task 后续变化污染已创建 Context。
4. **测试失败先判断来源。** `8f2ee6d` 曾是测试文件缺少 `deepcopy` import，而非业务代码错误。
5. **架构节点必须小步推进。** 一次只修改一个边界；用户本地全量通过后才 Push；Push 后才记录最终 SHA。
6. **AgentContext 迁移先保留 Task 兼容入口。** `BaseAgent.build_context()` 是逐 Agent 迁移的桥梁。
7. **Architect 是低风险迁移样板。** Architect 无 Tool Loop、无质量门禁副作用。
8. **Developer 暴露了 dependency snapshot 边界。** 通过 `dependency_context` 正式解决，而不是继续从 `task.context` 隐式取值。
9. **Tester / Reviewer 迁移必须保持质量门禁语义不变。** 本节点不得顺便修改 Workflow。

---

# 9. Commit Ledger

| 状态 | Commit | 说明 |
|---|---|---|
| <span style="color:green">√</span> | `63eea6c` | restore tester workflow execution |
| <span style="color:green">√</span> | `5a86044` | context flow integration tests |
| <span style="color:green">√</span> | `e2d31f3` | project execution test orchestrator |
| <span style="color:green">√</span> | `3d9f2e3` | canonicalize agent results |
| <span style="color:green">√</span> | `6528bf2` | AgentResult legacy compatibility |
| <span style="color:green">√</span> | `7bb371b` | AgentResult compatibility contract |
| <span style="color:green">√</span> | `5bc0575` | tester/reviewer AgentResult standardization |
| <span style="color:green">√</span> | `8f2ee6d` | AgentContext deepcopy test fix |
| <span style="color:green">√</span> | `0118003` | record Phase 3.1a |
| <span style="color:green">√</span> | `8d0745b` | BaseAgent context bridge contract tests |
| <span style="color:green">√</span> | `2786309` | BaseAgent AgentContext compatibility bridge |
| <span style="color:green">√</span> | `ae729f4` | ArchitectAgent → AgentContext |
| <span style="color:green">√</span> | `4a848c7` | DeveloperAgent AgentContext contract coverage |
| <span style="color:green">√</span> | `39102e5` | AgentContext serialization compatibility |
| <span style="color:green">√</span> | `483be86` | AgentContext dependency snapshot coverage / 3.1c final SHA |
| ☐ | **pending** | Phase 3.1d Tester / Reviewer → AgentContext |

---

# 10. 当前执行清单

### Phase 3.1a

- [x] BaseAgent context bridge
- [x] contract tests
- [x] 全量 pytest
- [x] 用户 Push
- [x] SHA 记录

### Phase 3.1b

- [x] ArchitectAgent 使用 AgentContext
- [x] contract tests
- [x] 全量 pytest
- [x] 用户 Push
- [x] `ae729f4` 记录

### Phase 3.1c

- [x] 检查 Developer 所需上下文
- [x] 增加 `dependency_context`
- [x] DeveloperAgent 使用 AgentContext
- [x] serialization compatibility
- [x] contract tests
- [x] 全量 pytest
- [x] 用户 Push
- [x] `483be86` 记录

### Phase 3.1d

- [ ] TesterAgent 使用 `build_context()`
- [ ] ReviewerAgent 使用 `build_context()`
- [ ] 保持 Tester / Reviewer AgentResult 语义
- [ ] 增加 Tester / Reviewer AgentContext contract tests
- [ ] 专项测试
- [ ] 全量 `pytest -q`
- [ ] 用户 Push
- [ ] 记录最终 SHA
- [ ] DevPlan 3.1d → √

**当前开发入口：Phase 3.1d — Tester / Reviewer → AgentContext。**
