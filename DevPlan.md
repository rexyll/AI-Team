# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Push → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 3 — AgentContext 正式化**

最新用户本地 / 远程同步 HEAD：

```text
c9ce052 (HEAD -> refactor/runtime-architecture, origin/refactor/runtime-architecture)
test: add AgentContext role visibility contract
```

最新全量测试：

```text
pytest -q
404 passed in 3.22s
```

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

**结论：Phase 3.4.2 Agent-specific context visibility 已完成。四类 Agent 的 Context 可见性现在由 role-specific projection + Contract Tests 双重约束；下一阶段不再扩大 Context 字段，而是治理 execution context 的只读语义。**

## ☐ 3.4.3 Read-only execution context convention

下一节点：建立 AgentContext 的 **read-only execution convention**。

重点不是立即引入复杂不可变对象，而是先用 Contract Tests 明确：

- Agent 收到的是 execution snapshot，而不是 Task mutable state。
- Agent 不应通过 projection 修改 Context snapshot 后影响后续 Agent。
- `context_view()` 返回值只能作为 Agent 输入，不应被当作 Task 更新 API。
- Agent 执行过程中不得依赖对 `Task` / `task.context` 的隐式写入来传递结果。
- AgentResult 才是 Agent → Workflow 的显式输出边界。
- Context history / current result / metadata 的更新应由 Runtime / TaskManager 负责，而不是 Agent prompt 构建逻辑负责。

第一步仍然是 Contract Tests；只有发现真实 Runtime 缺口才修改生产代码。

## ☐ 3.4.4 Legacy Task context retirement plan

### 目标

Phase 3.4 不再继续增加 AgentContext 字段，而是开始治理 **Context 生命周期、字段访问权限以及 Legacy Task context 的退出路径**。

严格要求：

- Agent 不直接读取或修改 Task mutable state。
- AgentContext 作为 execution snapshot 使用。
- 明确不同 Agent 能读取哪些 Context 字段。
- 明确 current result 与 history 的访问边界。
- 明确 `task.context` compatibility bridge 的剩余使用点。
- 只有 Contract Test 暴露真实缺口时才修改生产代码。

验收流程仍保持：

```text
GitHub 原始代码审计
        ↓
Access Policy Contract Tests
        ↓
专项测试
        ↓
必要时最小生产代码修改
        ↓
本地全量 pytest
        ↓
用户 Push
        ↓
最终 Commit SHA
        ↓
DevPlan √
        ↓
下一节点
```

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
14. Access Policy 测试应验证语义字段是否暴露，而不是绑定具体 dict 字符串序列化格式。
15. Agent-specific visibility 应通过统一 projection 约束，不能在各 Agent 中各自实现一套字段过滤逻辑。

---

# 当前开发入口

**Phase 3.4 — Context Lifecycle / Access Policy。**

下一步执行 **3.4.3 Read-only execution context convention：先建立 Contract Tests，验证 AgentContext / context_view 的只读执行语义及 Agent → AgentResult → Runtime 的结果边界。只有 Contract Test 暴露真实缺口时才修改 Runtime。**
