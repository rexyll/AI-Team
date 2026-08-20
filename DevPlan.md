# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Push → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 3 — AgentContext 正式化 / Context Lifecycle Governance**

最新用户本地 / 远程同步 HEAD：

```text
9c8afc5 (HEAD -> refactor/runtime-architecture, origin/refactor/runtime-architecture)
test: define legacy Task context retirement boundary
```

最新全量测试：

```text
pytest -q
414 passed in 16.69s
```

工作树：clean。

---

# Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.1a BaseAgent → AgentContext

完成 `BaseAgent.build_context()` compatibility bridge，保持 `run(Task) -> AgentResult` 外部契约。

- `2786309` — `feat: add BaseAgent AgentContext compatibility bridge`

## <span style="color:green">√</span> 3.1b ArchitectAgent → AgentContext

Architect 内部通过 `build_context()` 消费 AgentContext，保持 AgentResult 与 `data["architecture"]` 兼容语义。

- `ae729f4` — `feat: migrate architect agent to AgentContext`

## <span style="color:green">√</span> 3.1c DeveloperAgent → AgentContext

Developer 迁移到 AgentContext，并正式补齐 `dependency_context`，使 completed Architect result 能无损进入 Developer context。

最终用户 Push SHA：

- `483be86` — `test: cover AgentContext dependency snapshots`

验收：

```text
373 passed in 31.93s
```

## <span style="color:green">√</span> 3.1d Tester / Reviewer → AgentContext

Tester / Reviewer 均通过 `BaseAgent.build_context()` 使用 AgentContext；未修改 Workflow、TaskManager、Task lifecycle 或 Quality Gate。

最终用户 Push SHA：

- `2237e65` — `test: fix TesterAgent pytest collection warning`

验收：

```text
377 passed
0 warnings
```

---

# Phase 3.2 — Context Snapshot 完整化

## <span style="color:green">√</span> 3.2.1 Snapshot isolation contract

已通过 Contract Tests 固化以下契约：

- Task → AgentContext 深层数据隔离。
- AgentContext → Task 深层数据隔离。
- nested dict/list 等复杂 payload 的 deep-copy 隔离。
- completed dependency snapshot 隔离。
- pending / missing dependency 不进入 dependency snapshot。
- `to_dict()` / `from_dict()` 保持独立对象语义。
- legacy `task.context` dependency snapshot compatibility path 同样保持 deep-copy。

新增：

```text
tests/test_agent_context_snapshot.py
```

最终用户 Push SHA：

- `ad786e8` — `test: add AgentContext snapshot isolation contract coverage`

验收：

```text
383 passed in 18.29s
```

**结论：当前 AgentContext snapshot 核心实现满足隔离契约。只有 Contract Test 暴露真实缺口时才修改 Runtime。**

---

# Phase 3.3 — Context History

## <span style="color:green">√</span> 3.3.1 History Contract + History Snapshot

已完成 History Contract 定义及最小 Runtime 实现，统一以下三个独立历史流：

```text
AgentContext
├── history          ← lifecycle history
├── test_history     ← Tester execution history
└── review_history   ← Reviewer execution history
```

同时保持当前结果与历史记录分离：

```text
tester_feedback  ← 当前 Tester Result
reviewer_feedback ← 当前 Reviewer Result
```

已完成：

- `Task.status_history` → `AgentContext.history`。
- `Task.test_history` → `AgentContext.test_history`。
- `Task.review_history` → `AgentContext.review_history`。
- 三类 history 均进行 deep-copy snapshot isolation。
- AgentContext → Task 不产生反向污染。
- `to_dict()` / `from_dict()` 支持三类 history。
- 新增 history 字段保持旧序列化格式兼容：空 history 不强制输出。
- Developer revision / Tester / Reviewer execution history 保持独立语义。

新增 Contract Tests：

```text
tests/test_agent_context_history.py
```

最终用户 Push SHA：

- `73756eb` — `fix: preserve AgentContext history serialization compatibility`

本节点相关实现 commits：

- `97117c3` — `feat: add test and review history to AgentContext`
- `7613388` — `feat: expose test and review history in AgentContext`
- `73756eb` — `fix: preserve AgentContext history serialization compatibility`

验收：

```text
392 passed in 17.69s
0 warnings
```

**结论：Context History Contract 已完成并通过全量测试。AgentContext 现在具备独立的 lifecycle / test / review execution history snapshot。**

---

# Phase 3.4 — Context Lifecycle / Access Policy

## <span style="color:green">√</span> 3.4.1 Context field access policy

已完成 AgentContext 的 role-specific context projection，并建立 Agent-specific field access boundary。

核心原则：

```text
AgentContext
     │
     ▼
context_view(context, role)
     │
     ├── Architect  → architecture/task/dependency context
     ├── Developer  → implementation/dependency/test/review context
     ├── Tester     → task/result/test evidence
     └── Reviewer   → task/developer/test/dependency/review context
```

本节点完成：

- `context_view()` 按 Agent role 返回允许字段的 deep-copy projection。
- Runtime access projection 不再依赖 `AgentContext.to_dict()` 的可选序列化字段。
- 保持 `to_dict()` 的 legacy serialization compatibility，不因 Access Policy 改变空字段序列化行为。
- Architect 不暴露 Tester / Reviewer execution feedback。
- Tester 不暴露 metadata、review/internal execution state。
- Reviewer 按 policy 获取 upstream `dependency_context`、review context 与 metadata。
- Developer 正确消费 `dependency_context` 的语义化 upstream snapshot。
- 建立并修正 Access Policy Contract Tests，覆盖允许字段、禁止字段以及 dependency context 的语义化渲染。
- 保持 `run(Task) -> AgentResult` 外部兼容入口。

本节点相关 commits：

- `458f8ed` — `fix: enforce Architect AgentContext access policy`
- `47d8f4e` — `fix: enforce Developer AgentContext access policy`
- `4cb4ef6` — `fix: enforce Tester AgentContext access policy`
- `dcce73d` — `fix: enforce Reviewer AgentContext access policy`
- `aece0d2` — `fix: enforce AgentContext access policy projections`

最终用户 Push SHA：

- `aece0d2` — `fix: enforce AgentContext access policy projections`

验收：

```text
pytest -q
397 passed in 29.26s
```

**结论：Phase 3.4.1 Context field access policy 已完成。Agent prompt 的 Context 输入现在经过 role-specific projection；Context 运行时投影与序列化兼容职责已经解耦。**

## <span style="color:green">√</span> 3.4.2 Agent-specific context visibility

已完成四类 Agent 的 Context 消费路径审计，并通过 Contract Tests 固化 role-specific visibility boundary。

本节点确认：

- Architect / Developer / Tester / Reviewer 的 prompt 构建均通过 `context_view()` 获取受控 projection。
- Agent execution path 不直接依赖 `AgentContext.to_dict()` 作为运行时输入。
- 禁止字段不会因为 Context snapshot 中存在而自动进入 Agent prompt。
- `metadata`、`history`、`test_history`、`review_history`、`tester_feedback`、`reviewer_feedback` 按 role policy 控制可见性。
- `dependency_context` 作为语义化 upstream snapshot 受 policy 控制，不允许通过其他 Context 字段绕过权限边界。
- Contract Tests 不绑定 dict 的具体字符串序列化格式，而验证字段语义是否真正暴露 / 隐藏。
- projection 返回 deep-copy，Agent 对 projection 的修改不会污染原始 AgentContext。

新增 Contract Test：

```text
tests/test_agent_context_visibility.py
```

最终用户 Push SHA：

- `c9ce052` — `test: add AgentContext role visibility contract`

验收：

```text
pytest -q
404 passed in 3.22s
```

**结论：Phase 3.4.2 Agent-specific context visibility 已完成。四类 Agent 的 Context 可见性现在由 role-specific projection + Contract Tests 双重约束。**

## <span style="color:green">√</span> 3.4.3 Read-only execution context convention

已通过 Contract Tests 固化 AgentContext 的只读 execution convention，当前不引入复杂 immutable object，而是明确 execution snapshot 的所有权边界。

本节点确认：

- Agent 收到的是 execution snapshot，而不是 Task mutable state。
- `ContextBuilder` 构建的 AgentContext 对 Task 的 result / context / test result / review result / history 均保持 deep-copy 隔离。
- `context_view()` 返回值只能作为 Agent 输入；对 projection 的 mutation 不会反向修改 AgentContext。
- Agent execution path 不通过 projection 作为 Task 更新 API。
- 重新构建 AgentContext 会重新从 runtime-owned Task state 获取 snapshot，不会保留 Agent 对旧 projection 的修改。
- current result 与 lifecycle / test / review history 均由 Runtime / TaskManager 所有。
- AgentContext 不提供 `update_task`、`set_status`、`record_test_result`、`record_review_result` 等 Task mutation API。
- AgentResult 保持 Agent → Workflow 的显式输出边界。

新增 Contract Test：

```text
tests/test_agent_context_read_only.py
```

最终用户 Push SHA：

- `8ef9e19` — `test: add AgentContext read-only execution contract`

验收：

```text
pytest -q
409 passed in 21.37s
```

随后针对 Legacy Task.context boundary 的新增 Contract Tests 继续运行全量回归：

```text
pytest -q
414 passed in 16.69s
```

**结论：Phase 3.4.3 Read-only execution context convention 已完成。AgentContext 已明确为 runtime-owned execution snapshot；Agent 不再拥有 Task mutation 语义。**

## <span style="color:green">√</span> 3.4.4 Legacy Task.context retirement boundary

已完成 Legacy `Task.context` 的第一阶段退出边界定义。当前不删除 compatibility bridge，而是通过 Contract Tests 固化其允许的最小职责。

### Legacy context 当前唯一允许的兼容职责

```text
Task.dependencies
        │
        ▼
legacy task.context[dependency_id]
        │
        ▼
AgentContext.dependency_context
```

同时：

- 只有 `task.dependencies` 中声明的 dependency snapshot 才允许从 legacy context 进入 `dependency_context`。
- 未声明的 legacy context snapshot 不得泄漏。
- legacy dependency snapshot 不得重复进入 `AgentContext.metadata`。
- legacy reserved keys 不得覆盖 canonical `task_result` / `tester_feedback` / `reviewer_feedback`。
- legacy `result` / `status_history` / `test_history` / `review_history` 不再作为 execution result/history 的来源。
- 非 dependency 的 legacy context 数据只能作为 metadata compatibility data 保存。
- 当 `all_tasks` 中存在 completed dependency 时，canonical Task snapshot 优先于 legacy context snapshot。

新增 Contract Test：

```text
tests/test_legacy_task_context_boundary.py
```

最终用户 Push SHA：

- `9c8afc5` — `test: define legacy Task context retirement boundary`

验收：

```text
pytest -q
414 passed in 16.69s
```

**结论：Phase 3.4.4 Legacy Task.context retirement boundary 已完成第一阶段。下一步不是直接删除 `Task.context`，而是继续审计并消除 runtime 中非必要的 legacy context 读取点。**

### 下一阶段 3.4.5 — Legacy context usage inventory

目标：建立 `Task.context` 的完整 runtime usage inventory，并把每个读取点分类为：

```text
A. canonical runtime data source → 必须迁移
B. dependency compatibility bridge → 暂时保留
C. metadata compatibility → 明确保留范围
D. dead / redundant usage → 删除
```

执行纪律：

1. 先 GitHub 原始代码搜索 / 审计。
2. 先添加 Contract Tests 或 usage inventory tests。
3. 只有测试暴露真实 runtime 缺口时才修改生产代码。
4. 每次只消除一类 legacy usage。
5. 每个小节点都跑专项测试 + 全量 `pytest -q`。
6. Phase 3 完成前不得提前进入 Workflow / LLM 大规模重构。

---

# Phase 4 — LLM Abstraction

## ☐ 4.1 BaseLLM 完整实现
## ☐ 4.2 MockLLM
## ☐ 4.3 Agent → BaseLLM
## ☐ 4.4 Workflow → LLM-independent
## ☐ 4.5 Provider/config 可替换

# Phase 5 — Tool / Sandbox Architecture

## ☐ 5.1 Tool Contract
## ☐ 5.2 Tool Registry Contract
## ☐ 5.3 Tool Argument Validation
## ☐ 5.4 Workspace Sandbox
## ☐ 5.5 Tool Permission Policy
## ☐ 5.6 Tool Error Contract

# Phase 6 — Workflow / Project Orchestrator

## ☐ 6.1 TaskWorkflow 状态机
## ☐ 6.2 Dependency-aware Scheduler
## ☐ 6.3 ProjectOrchestrator
## ☐ 6.4 Task 并行执行
## ☐ 6.5 Retry / Resume
## ☐ 6.6 ProjectResult

# Phase 7 — Persistence / Observability

## ☐ 7.1 Task persistence
## ☐ 7.2 Project persistence
## ☐ 7.3 Agent execution records
## ☐ 7.4 Tool execution logs
## ☐ 7.5 Workflow event log
## ☐ 7.6 Resume from persisted state

# Phase 8 — Production Hardening

## ☐ 8.1 Contract Tests
## ☐ 8.2 Failure Injection Tests
## ☐ 8.3 Security Tests
## ☐ 8.4 LLM Mock Integration Tests
## ☐ 8.5 Long-running Workflow Tests
## ☐ 8.6 Performance / Concurrency Tests
## ☐ 8.7 Documentation / Examples

# Commit Ledger

| 状态 | Commit | 节点 |
|---|---|---|
| <span style="color:green">√</span> | `2786309` | BaseAgent → AgentContext |
| <span style="color:green">√</span> | `ae729f4` | ArchitectAgent → AgentContext |
| <span style="color:green">√</span> | `483be86` | DeveloperAgent → AgentContext |
| <span style="color:green">√</span> | `2237e65` | Tester / Reviewer → AgentContext |
| <span style="color:green">√</span> | `ad786e8` | Context Snapshot isolation contract |
| <span style="color:green">√</span> | `73756eb` | Context History contract + snapshot |
| <span style="color:green">√</span> | `aece0d2` | Context field access policy |
| <span style="color:green">√</span> | `c9ce052` | Agent-specific context visibility contract |
| <span style="color:green">√</span> | `8ef9e19` | AgentContext read-only execution contract |
| <span style="color:green">√</span> | `9c8afc5` | Legacy Task.context retirement boundary |

---

# 重要经验

1. Workflow 不能绕过 Tester；质量门禁修改必须先跑完整 Developer → Tester → Reviewer 集成测试。
2. AgentResult 必须保持 legacy compatibility API。
3. AgentContext 必须是 deep-copy snapshot，不能让 Agent 执行污染 Task。
4. 测试失败先判断业务代码、测试代码还是环境问题，禁止盲目修改生产代码。
5. AgentContext 迁移必须保持 `run(Task) -> AgentResult` 外部兼容入口。
6. Developer 暴露的 dependency snapshot 缺口通过 `dependency_context` 正式解决，而不是继续读取 `task.context`。
7. Tester / Reviewer 迁移不得顺便修改 Workflow。
8. pytest warning 应在测试侧最小修复，不污染生产代码。
9. Phase 3.2 已用 Contract Tests 证明 snapshot isolation，不为了产生生产 commit 而改 Runtime。
10. Phase 3.3 已统一 lifecycle / test / review History Contract，并保持序列化兼容。
11. 新增 Context 字段必须先建立 Contract Test，再进行最小 Runtime 修改。
12. Context Access Policy 必须通过 role-specific projection 实现，不能让 Agent 依赖 `to_dict()` 的序列化字段存在性。
13. Runtime projection 与 persistence serialization 必须保持职责分离，避免 legacy compatibility 反向限制运行时访问控制。
14. Read-only execution context 优先通过 snapshot isolation + Contract Tests 建立所有权边界，不急于引入复杂 immutable abstraction。
15. Legacy `Task.context` 退出必须先定义兼容边界，再逐步清除非必要读取点，不能一次性删除导致隐式依赖回归。
16. Canonical runtime state 必须优先于 legacy compatibility data；compatibility bridge 只能补充不能覆盖 canonical fields。

---

# 当前下一动作

**3.4.5 Legacy context usage inventory**

先审计：

```text
Task.context
    ↓
所有 runtime / agents / workflow / task_manager 读取点
    ↓
分类 canonical / compatibility / metadata / dead usage
    ↓
Contract Test
    ↓
最小迁移
```

完成 3.4.5 后，再决定是否需要 3.4.6 compatibility bridge 最小化；只有当 `Task.context` 已没有非必要 runtime 读取点时，才进入 Phase 3 收尾与 Phase 4 LLM Abstraction。
