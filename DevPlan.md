# AI-Team 开发计划与开发历史

> 项目：`rexyll/AI-Team`  
> 当前分支：`refactor/runtime-architecture`  
> 本文件是 Development Ledger：已完成能力使用绿色 `√`；进行中能力使用 `☐`；每个重要节点记录测试结果、commit SHA 与经验，避免重复踩坑。

---

# 1. 当前状态

## 1.1 稳定基线

用户本地最新验证：

```text
pytest -q
362 passed in 21.11s
```

**当前基线：362 passed / 0 failed。**

最近稳定节点：

- `ae729f4` — `feat: migrate architect agent to AgentContext`
- `8f2ee6d` — `test: fix agent context deepcopy import`
- `5bc0575` — `feat: standardize tester and reviewer agent results`
- `7bb371b` — `fix: complete AgentResult compatibility contract`
- `2786309` — `feat: add BaseAgent AgentContext compatibility bridge`

## 1.2 当前阶段

**Phase 3 — AgentContext 正式化。**

Phase 0/1 已建立并稳定 Task Lifecycle、Developer → Tester → Reviewer Quality Gate、Review Loop、Dependency、ContextBuilder、Project Execution；Phase 2 已完成 AgentResult 统一契约；Phase 3.1a 已完成 BaseAgent 到 AgentContext 的兼容桥接；Phase 3.1b 已完成 ArchitectAgent 迁移，现在进入 DeveloperAgent 的第一轮迁移。

**当前节点：Phase 3.1c — DeveloperAgent → AgentContext 迁移。**

---

# 2. 总体目标

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

质量门禁始终保持：

```text
Developer → Tester FAILED → Developer revision → Tester
Developer → Tester PASSED → Reviewer
                         ├→ REVISION → Developer
                         └→ APPROVED → Complete
```

最终 Runtime 必须具备：可测试、可恢复、可扩展、可替换 LLM、安全 Tool/Sandbox、明确 Task/Agent/Project Contract、依赖调度、未来并行、持久化和可观测性。

---

# 3. 已完成历史

## Phase 0 — 基础骨架

### <span style="color:green">√</span> 0.1 多 Agent 基础结构

已建立 Planner / Architect / Developer / Tester / Reviewer，以及 Task / Workflow / Router / Factory 等 Runtime 模块。

### <span style="color:green">√</span> 0.2 Developer + Workspace Sandbox

Developer 具备受保护工作区、Tool Registry、文件读取/修改、测试/构建和 Tool Loop 上限。

关键 commits：

- `f9c42858fa3523b000428ff53bc6126bdd88ecac` — establish developer agent with workspace sandbox
- `60ac4e8cea7986735e0d44fdb55e1cf9a92ea1a7` — establish developer agent with workspace sandbox
- `c9b02371389440926e667a73388ed837f5cace9f` — pass reviewer feedback and bound tool loop
- `1e8255d471396b3a49ca1c7184d5e9b35c4f1709` — correct terminal command policy

### <span style="color:green">√</span> 0.3 TaskManager / Workflow

TaskManager 成为状态变更核心入口，Workflow 负责 orchestration。

- `75fcfe77746302d8f623e60052acd4b9adaddf78` — keep task state transitions inside TaskManager
- `dfb21a515c3f6896530f167bcf49332d63657b34` — centralize workflow execution and failure handling
- `7592dbeece2d14f9fea9a7bd21dbe568401dc2f2` — route developer tasks through TaskWorkflow
- `43108ad45f271f117a298b90d8414c56b313061d` — centralize workflow transitions and review history

## Phase 1 — Lifecycle / Quality Gate

### <span style="color:green">√</span> 1.1 Task Lifecycle

```text
pending → ready → running → reviewing → review_pending → completed
```

### <span style="color:green">√</span> 1.2 Tester Quality Gate

Reviewer 只有在 Tester `passed` 后才能运行；Tester `failed` 回到 Developer。

- `7b1e78b06e45280ce2ad4c8b5a4049f044b01936` — dedicated tester agent
- `458f80504da4b4f116249e776593013619cf2cc7` — register tester agent
- `9ce87012603ac851f13611dc63416df2f9faf825` — enforce quality gate
- `63eea6c37c995b167e1fd3431b10c01c9555bae7` — restore tester workflow execution

### <span style="color:green">√</span> 1.3 Reviewer Revision Loop

支持 `APPROVED` / `REVISION_REQUIRED` 与 `max_review_rounds`。

- `f8d8e2f24913f85c24cd7793bdc4febaaeac755c` — structured review history
- `0d57e82c5c9942ceeeae552af10dc7f75d21423c` — simplify workflow result handling

### <span style="color:green">√</span> 1.4 Tester / Reviewer History

支持 `test_result`、`test_history`、`review_result`、`review_history`，覆盖重复记录和 revision round。

### <span style="color:green">√</span> 1.5 Workflow Result Handling

Tester / Reviewer handling 已从主流程抽离。

**经验：** 曾发生 Workflow 简化绕过 Tester 的回归；以后任何 Workflow 重构必须先跑 Developer → Tester → Reviewer 集成测试。

## Phase 1.5 — Dependency / Context

### <span style="color:green">√</span> 1.6 Dependency Graph

支持依赖并拒绝循环依赖。

- `4584078663bd8dc8b056a8d7599dc950ffc338b0` — reject cyclic dependencies

### <span style="color:green">√</span> 1.7 ContextBuilder

提供 completed dependency result、Tester feedback、Reviewer feedback，并保证不修改 Task、不执行 Agent、不控制 Workflow。

- `ffad04127062dab03bb192e3cf0dbfa46092baa7` — preserve legacy task context API
- `5a860447d95fb87da5d56c4f7efbf50e11e95f15` — context flow integration tests

### <span style="color:green">√</span> 1.8 Reviewer Feedback → Developer Context

- `c9b02371389440926e667a73388ed837f5cace9f`

## Phase 1.6 — Planning / Orchestration

### <span style="color:green">√</span> 1.9 Planner / PlanBuilder / Project Execution

- `e2d31f3fc0e5e9873893dd69f786994411b03b35` — fix project execution test orchestrator

### <span style="color:green">√</span> 1.10 Agent Factory / Registry / Configuration

- `529ca53c004fb30569e935e58a6419461f7167a0` — centralized task workflow factory
- `79413eb445c1951d6d33948c23df09e11551ecb8` — custom configuration validation

---

# 4. Phase 2 — AgentResult Contract

### <span style="color:green">√</span> 2.1 AgentResult

统一结构：

```python
AgentResult(status, agent, task_id, message, data)
```

- `3d9f2e3599774b4ca4e9184107f6419ccc4176ee` — canonicalize agent results

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

旧 Agent-specific payload 归一化到 `data`，并保持 legacy dictionary-style access。

- `6528bf27e4a820c1eea2f0a98d1030e4c47f6599` — AgentResult legacy compatibility

### <span style="color:green">√</span> 2.4 Result Normalizer

已建立 `runtime/result_normalizer.py`。

### <span style="color:green">√</span> 2.5 所有 Agent 返回 AgentResult

Architect / Developer / Tester / Reviewer 已统一。

- `7bb371be68a9b2c9c9c94026efd06928b8e6817f` — complete AgentResult compatibility contract

### <span style="color:green">√</span> 2.6 BaseAgent 类型契约

`run(task: Task) -> AgentResult` 已明确。

### <span style="color:green">√</span> 2.7 AgentResult Compatibility API

完成 `from_any()`、`succeeded`、`failed`、`requires_revision`、legacy payload direct access 和 core-field validation。

### <span style="color:green">√</span> 2.8 Tester / Reviewer Result 标准化

- `5bc0575` — standardize tester and reviewer agent results

专项验证：

```text
pytest tests/test_developer_result.py -q   → 5 passed
pytest tests/test_agent_result.py -q       → 36 passed
pytest tests/test_task_lifecycle.py -q    → 23 passed
pytest tests/test_context_flow.py -q       → 10 passed
```

### <span style="color:green">√</span> 2.9 AgentContext Snapshot 基础能力

AgentContext 已具备字段校验、deep-copy snapshot、`to_dict()`、`from_dict()`、dictionary-style access。

- `8f2ee6d` — fix agent context deepcopy import

---

# 5. Phase 3 — AgentContext 正式化

### <span style="color:green">√</span> 3.1a BaseAgent AgentContext compatibility bridge

目标：在不破坏现有 `agent.run(task)` 调用链的情况下建立：

```text
Task → ContextBuilder → AgentContext
```

已完成：

- `agents/base.py` 增加 `build_context()`。
- `build_context()` 自动使用 Agent 的 `role`。
- 支持 `all_tasks`，保留 dependency snapshot。
- 保持现有 `run(Task)` 兼容入口不变。
- 增加 BaseAgent context bridge contract tests。
- AgentContext 与 Task 保持 snapshot 隔离。

实现 commits：

- `0118003` — update DevPlan and enter Phase 3.1a
- `8d0745b` — add BaseAgent context bridge contract tests
- `2786309` — `feat: add BaseAgent AgentContext compatibility bridge`

验收结果：

```text
pytest -q
362 passed in 21.11s
```

**Phase 3.1a 正式完成。**

### <span style="color:green">√</span> 3.1b ArchitectAgent → AgentContext 迁移

目标：Architect 保留 `run(Task) -> AgentResult` 外部兼容契约，但内部不再直接从 Task 拼装执行 prompt，而是通过：

```text
Task
 ↓
BaseAgent.build_context()
 ↓
AgentContext
 ↓
Architect prompt
 ↓
AgentResult
```

本节点只允许修改 ArchitectAgent 与对应 contract tests，不修改 Workflow、TaskManager、Task 生命周期和 ContextBuilder 核心逻辑。

已完成：

- `ArchitectAgent.run(Task)` 保持外部兼容入口。
- Architect 内部通过 `build_context()` 获取 AgentContext。
- Prompt 改为消费 AgentContext 字段。
- canonical `AgentResult` 与 `data["architecture"]` 兼容语义保持不变。
- 增加 Architect AgentContext contract tests。
- 保持 Agent 不修改原 Task。

最终 commit：

- `ae729f43756f09573d4855ce0722b4f023661483` — `feat: migrate architect agent to AgentContext`

验收结果：

- 用户已完成代码 push。
- `ae729f4` 已成为 `refactor/runtime-architecture` 与 `origin/refactor/runtime-architecture` 的共同 HEAD。
- 本节点专项测试与全量 `pytest -q` 已按迁移门禁完成后进入下一节点。

**Phase 3.1b 正式完成。**

### ☐ 3.1c DeveloperAgent → AgentContext 迁移

Developer 最终消费 task_id、task_title、task_description、dependencies、task_result、tester_feedback、reviewer_feedback、history、metadata。

迁移原则：

- 保持 `run(Task) -> AgentResult` 外部兼容契约。
- 保持 Developer Tool Loop、Tool Registry、Tool Guard、changed_files、test evidence 和 `AgentResult.data` 语义不变。
- Prompt 从 Task 字段迁移到 AgentContext 字段。
- 不修改 Workflow、TaskManager、Task 生命周期和质量门禁。
- 不把本节点的 AgentContext 缺口通过扩大 Workflow 改造来解决。
- 若发现 AgentContext 无法无损承载现有 Developer 必需上下文，先停在边界处记录缺口，再决定是否进入 3.2，而不是引入隐式兼容逻辑。

验收重点：

- Developer 必须调用 `build_context()`。
- Prompt 使用 AgentContext 的 task_id / task_title / task_description / role / status / dependencies / task_result / tester_feedback / reviewer_feedback / history / metadata。
- Developer Tool Loop 行为保持不变。
- canonical `AgentResult` 保持不变。
- 不允许 Agent 修改 Task。
- 专项测试通过后才能执行全量 `pytest -q`。
- 全量通过后由用户 Push，再记录最终 commit SHA。

### ☐ 3.1d Tester / Reviewer 迁移

最后迁移 Tester / Reviewer，以降低质量门禁回归风险。

### ☐ 3.2 Context Snapshot 完整化

必须保持 Agent 不修改原 Task；dependency context 是 snapshot；未完成 dependency 不暴露；Tester / Reviewer 只获得执行所需信息。

### ☐ 3.3 Context History

统一暴露 lifecycle / test / review history。

---

# 6. 后续开发路线

## Phase 4 — LLM Abstraction

### ☐ 4.1 BaseLLM 完整实现
### ☐ 4.2 MockLLM
### ☐ 4.3 Agent → BaseLLM
### ☐ 4.4 Workflow → LLM-independent
### ☐ 4.5 Provider/config 可替换

目标：测试完全脱离真实模型。

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

# 7. 重要问题与经验

1. **Workflow 不能绕过 Tester。** `63eea6c` 修复过该回归；今后 Workflow 重构先跑完整质量门禁集成测试。
2. **AgentResult 必须兼容旧 API。** `7bb371b` 修复了 agent/task_id 默认值、from_dict 校验、legacy payload direct access 等问题。
3. **AgentContext 必须是 snapshot。** 使用 deep copy，避免 Task 后续变化污染已创建 context。
4. **测试失败先判断来源。** `8f2ee6d` 是测试文件缺少 `deepcopy` import，而非业务代码错误。
5. **架构节点必须小步推进。** 一次只修改一个边界；用户本地全量测试通过后再 push；然后更新 DevPlan。
6. **AgentContext 迁移必须先保留 Task 兼容入口。** 先建立 `BaseAgent.build_context()`，再逐 Agent 迁移内部逻辑，避免一次性改动 Workflow 和生命周期。
7. **Architect 是 AgentContext 迁移的第一个业务 Agent。** Architect 无 Tool Loop、无质量门禁副作用，适合作为低风险迁移样板；其成功后再迁移 Developer。
8. **Developer 迁移前必须检查上下文承载能力。** 当前 `ContextBuilder.build_agent_context()` 的 `dependencies` 只暴露已完成依赖的 ID，而 Developer 现有 prompt 还依赖完整 dependency result（尤其 Architect architecture）。3.1c 不得通过隐式兼容或扩大 Workflow 改造来掩盖这个边界问题。

---

# 8. Commit Ledger

| 状态 | Commit | 说明 |
|---|---|---|
| <span style="color:green">√</span> | `63eea6c` | restore tester workflow execution |
| <span style="color:green">√</span> | `5a86044` | context flow integration tests |
| <span style="color:green">√</span> | `e2d31f3` | project execution test orchestrator |
| <span style="color:green">√</span> | `3d9f2e3` | canonicalize agent results |
| <span style="color:green">√</span> | `6528bf2` | AgentResult legacy compatibility |
| <span style="color:green">√</span> | `7bb371b` | AgentResult compatibility contract |
| <span style="color:green">√</span> | `5bc0575` | tester/reviewer AgentResult standardization |
| <span style="color:green">√</span> | `8f2ee6d` | agent context deepcopy test fix |
| <span style="color:green">√</span> | `0118003` | record Phase 3.1a and enter Architect migration |
| <span style="color:green">√</span> | `8d0745b` | BaseAgent context bridge contract tests |
| <span style="color:green">√</span> | `2786309` | BaseAgent AgentContext compatibility bridge |
| <span style="color:green">√</span> | `ae729f4` | ArchitectAgent → AgentContext migration |
| ☐ | **pending** | Phase 3.1c DeveloperAgent → AgentContext migration |

---

# 9. 当前执行清单

### Phase 3.1a

- [x] 更新 `agents/base.py`
- [x] 增加 BaseAgent context bridge tests
- [x] 保证现有 Agent / Workflow 行为不变
- [x] 用户执行 `pytest -q`
- [x] 记录 Phase 3.1a commits

### Phase 3.1b

- [x] 读取并修改 `agents/architect.py`
- [x] 增加 Architect AgentContext contract tests
- [x] 保持 `run(Task) -> AgentResult` 兼容入口
- [x] 保持 `data["architecture"]` 兼容语义
- [x] 用户执行专项测试
- [x] 用户执行 `pytest -q`
- [x] 用户 Push 正式 commit
- [x] 更新 DevPlan 记录最终 commit SHA

### Phase 3.1c

- [ ] 读取 GitHub 当前 `agents/developer.py`
- [ ] 先确认 AgentContext 是否能无损承载 Developer 当前依赖上下文
- [ ] 小范围修改 `agents/developer.py` 与对应 contract tests
- [ ] 保持 `run(Task) -> AgentResult` 兼容入口
- [ ] 保持 Developer Tool Loop / Tool Guard / Result evidence 语义
- [ ] 用户执行专项测试
- [ ] 用户执行 `pytest -q`
- [ ] 测试通过后由用户创建正式 commit
- [ ] 再次更新 DevPlan 记录最终 commit SHA

**当前开发入口：Phase 3.1c — DeveloperAgent → AgentContext 迁移。**
