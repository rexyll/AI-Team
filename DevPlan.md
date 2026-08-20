# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Push → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 4 — LLM Abstraction**

Phase 3 Context Lifecycle Governance 已完成主要退出边界；当前进入 LLM 抽象层建设。

最新远程 HEAD：

```text
d72f59b72ce9541deb5b983097ac1277661e9c30
test: define MockLLM deterministic contract
```

本轮此前完成：

```text
fa83b98d732ee651369babf19702d63edfb6db73
test: define BaseLLM generation contract
```

用户最近一次全量验收（MockLLM 提交之前）：

```text
pytest -q
428 passed in 2.78s
```

当前 MockLLM 已提交，但尚未由用户执行最新全量验收；下一步必须先专项测试，再全量 pytest。

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

已通过 Contract Tests 固化 Task / AgentContext 双向 deep-copy snapshot isolation、completed dependency snapshot、pending/missing dependency filtering，以及 `to_dict()` / `from_dict()` 独立对象语义。

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

**结论：AgentContext snapshot 核心实现满足隔离契约。**

---

# Phase 3.3 — Context History

## <span style="color:green">√</span> 3.3.1 History Contract + History Snapshot

统一三个独立历史流：

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

完成：

- `Task.status_history` → `AgentContext.history`
- `Task.test_history` → `AgentContext.test_history`
- `Task.review_history` → `AgentContext.review_history`
- 三类 history deep-copy isolation
- AgentContext → Task 不产生反向污染
- `to_dict()` / `from_dict()` 支持三类 history
- 空 history 保持旧序列化兼容
- Developer revision / Tester / Reviewer history 保持独立语义

新增：

```text
tests/test_agent_context_history.py
```

相关 commits：

- `97117c3` — `feat: add test and review history to AgentContext`
- `7613388` — `feat: expose test and review history in AgentContext`
- `73756eb` — `fix: preserve AgentContext history serialization compatibility`

验收：

```text
392 passed in 17.69s
0 warnings
```

**结论：Context History Contract 已完成。**

---

# Phase 3.4 — Context Lifecycle / Access Policy

## <span style="color:green">√</span> 3.4.1 Context field access policy

完成 role-specific `context_view(context, role)` projection，并解耦 runtime access projection 与 `AgentContext.to_dict()` legacy serialization。

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

完成：

- projection 按 role 返回允许字段的 deep-copy
- Architect 不暴露 Tester / Reviewer execution feedback
- Tester 不暴露 metadata、review/internal execution state
- Reviewer 按 policy 获取 upstream `dependency_context`、review context 与 metadata
- Developer 正确消费语义化 `dependency_context`
- Access Policy Contract Tests 覆盖允许/禁止字段和 dependency context 语义化渲染
- 保持 `run(Task) -> AgentResult` 外部兼容入口

相关 commits：

- `458f8ed` — `fix: enforce Architect AgentContext access policy`
- `47d8f4e` — `fix: enforce Developer AgentContext access policy`
- `4cb4ef6` — `fix: enforce Tester AgentContext access policy`
- `dcce73d` — `fix: enforce Reviewer AgentContext access policy`
- `aece0d2` — `fix: enforce AgentContext access policy projections`

验收：

```text
pytest -q
397 passed in 29.26s
```

**结论：Phase 3.4.1 已完成。**

## <span style="color:green">√</span> 3.4.2 Agent-specific context visibility

已完成四类 Agent Context 消费路径审计，并通过 Contract Tests 固化 role-specific visibility boundary。

确认：

- Architect / Developer / Tester / Reviewer 的 prompt 构建均通过 `context_view()`
- Agent execution path 不直接依赖 `AgentContext.to_dict()`
- 禁止字段不会因为 Context snapshot 存在而自动进入 prompt
- `metadata`、`history`、`test_history`、`review_history`、`tester_feedback`、`reviewer_feedback` 按 role policy 控制
- `dependency_context` 不允许通过其他字段绕过权限边界
- Contract Tests 验证语义而非具体 dict 序列化格式
- projection deep-copy 不污染原始 AgentContext

新增：

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

**结论：Phase 3.4.2 已完成。**

## <span style="color:green">√</span> 3.4.3 Read-only execution context convention

通过 Contract Tests 固化 AgentContext 只读 execution convention，以 snapshot isolation 明确所有权边界，不引入复杂 immutable abstraction。

确认：

- Agent 收到 execution snapshot，而不是 Task mutable state
- result / context / test result / review result / history 均 deep-copy 隔离
- `context_view()` 只能作为 Agent 输入
- Agent execution path 不通过 projection 更新 Task
- Runtime / TaskManager 拥有 current result 与 lifecycle/test/review history
- AgentContext 不提供 Task mutation API
- AgentResult 保持 Agent → Workflow 显式输出边界

新增：

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

**结论：Phase 3.4.3 已完成。**

## <span style="color:green">√</span> 3.4.4 Legacy Task.context retirement boundary

完成 Legacy `Task.context` 第一阶段退出边界定义。暂不删除 compatibility bridge，而是通过 Contract Tests 固化最小职责。

唯一允许的兼容职责：

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

- 只有 `task.dependencies` 中声明的 dependency snapshot 才允许进入 `dependency_context`
- 未声明 snapshot 不得泄漏
- legacy dependency snapshot 不得重复进入 `metadata`
- legacy reserved keys 不得覆盖 canonical `task_result` / `tester_feedback` / `reviewer_feedback`
- legacy `result` / `status_history` / `test_history` / `review_history` 不再作为 execution result/history 来源
- 非 dependency legacy context 数据只能作为 metadata compatibility data 保存
- `all_tasks` 中存在 completed dependency 时 canonical Task snapshot 优先

新增：

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

**结论：Phase 3.4.4 第一阶段已完成。**

## <span style="color:green">√</span> 3.4.5 Legacy context usage inventory

完成 `Task.context` runtime usage inventory，并建立分类 Contract Test，明确当前 Legacy Context 的剩余使用点属于兼容职责，而不是 canonical execution state source。

分类：

```text
A. canonical runtime data source → 必须迁移
B. dependency compatibility bridge → 暂时保留
C. metadata compatibility → 明确保留范围
D. dead / redundant usage → 删除
```

当前 inventory：

| Runtime usage | 分类 | 决策 |
|---|---|---|
| `ContextBuilder._build_dependency_context()` | B | 仅允许通过 `LegacyDependencyBridge` |
| `ContextBuilder._build_metadata()` | C | 保留非 reserved metadata compatibility |
| `TaskWorkflow._build_context()` | B | 仅维护 dependency compatibility bridge |
| canonical result/test/review/history 从 `Task.context` 读取 | A | 禁止 |
| dead / redundant legacy reads | D | 删除 / 不得新增 |

新增 Contract Test：

```text
tests/test_legacy_task_context_inventory.py
```

最终用户 Push SHA：

- `eb53804` — `test: add legacy Task.context usage inventory`

验收：

```text
pytest -q
417 passed in 37.56s
```

**结论：Phase 3.4.5 已完成。**

## <span style="color:green">√</span> 3.4.6 Legacy dependency bridge isolation

已将 Legacy dependency compatibility 收敛到独立 `LegacyDependencyBridge`，避免其他 runtime component 直接读取 dependency entries。

核心契约：

```text
canonical all_tasks[dependency_id]
        │
        ├── completed → canonical snapshot
        │
        └── unavailable → legacy fallback
                              │
                              ▼
                   LegacyDependencyBridge
                              │
                              ▼
                 AgentContext.dependency_context
```

完成：

- canonical completed dependency snapshot 始终优先
- canonical dependency 存在但未 completed 时不错误回退到 legacy snapshot
- legacy fallback 仅针对 `task.dependencies` 中声明的 dependency
- legacy snapshot 必须包含 `title` / `role` / `result`
- legacy dependency 数据统一 deep-copy
- `ContextBuilder` 仅通过 bridge 获取 dependency context
- 保持 `AgentContext.dependency_context` 稳定接口
- 不删除 `Task.context`，继续保留最小 compatibility boundary

当前实现：

```text
runtime/legacy_dependency_bridge.py
```

验收：

```text
pytest -q
424 passed in 11.84s
```

**结论：Phase 3.4.6 已完成。Phase 3 Context Lifecycle Governance 的主要 runtime 退出边界完成，进入 Phase 4。**

---

# Phase 4 — LLM Abstraction

## <span style="color:green">√</span> 4.1 BaseLLM Contract

已冻结 provider-independent `BaseLLM.generate()` 契约，暂不绑定具体供应商实现。

契约：

```text
BaseLLM.generate(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str
```

新增：

```text
tests/test_llm_base_contract.py
```

最终用户 Push SHA：

- `fa83b98d732ee651369babf19702d63edfb6db73` — `test: define BaseLLM generation contract`

验收：

```text
pytest -q
428 passed in 2.78s
```

**结论：4.1 BaseLLM Contract 已完成。**

## ☐ 4.2 MockLLM

目标：提供 deterministic、零外部网络依赖的 LLM 实现，用于单元测试、Agent 集成测试和后续 Workflow 测试。

当前实现已提交，等待用户专项 + 全量验收：

```text
runtime/llm/mock.py
tests/test_mock_llm.py
```

实现契约：

- 默认 deterministic response
- FIFO response queue
- fallback response
- invocation recording
- remaining response count
- reset call history
- BaseLLM compatibility
- 参数类型边界校验

提交：

- `e97132d2ffb6d2222932c6d4d2dff450d11b7cca` — `feat: add deterministic MockLLM implementation`
- `d72f59b72ce9541deb5b983097ac1277661e9c30` — `test: define MockLLM deterministic contract`

**下一步：先运行 `pytest tests/test_mock_llm.py -q`，通过后运行全量 `pytest -q`。**

## ☐ 4.3 Agent → BaseLLM

下一节点：将 Agent 中当前直接依赖 provider/model helper 的调用方式收敛到可注入 `BaseLLM`，保持现有 `run(Task) -> AgentResult` 外部契约不变。

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
| <span style="color:green">√</span> | `eb53804` | Legacy Task.context usage inventory |
| <span style="color:green">√</span> | `fa83b98d` | BaseLLM generation contract |
| <span style="color:green">√</span> | `e97132d2` | MockLLM implementation |
| <span style="color:green">√</span> | `d72f59b7` | MockLLM deterministic contract |

---

# 重要经验

1. Workflow 不能绕过 Tester；质量门禁修改必须先跑完整 Developer → Tester → Reviewer 集成测试。
2. AgentResult 必须保持 legacy compatibility API。
3. AgentContext 必须是 deep-copy snapshot，不能让 Agent 执行污染 Task。
4. 测试失败先判断业务代码、测试代码还是环境问题，禁止盲目修改生产代码。
5. AgentContext 迁移必须保持 `run(Task) -> AgentResult` 外部兼容入口。
6. Developer dependency snapshot 缺口通过 `dependency_context` 正式解决，而不是继续读取 `task.context`。
7. Tester / Reviewer 迁移不得顺便修改 Workflow。
8. pytest warning 应在测试侧最小修复，不污染生产代码。
9. Phase 3.2 用 Contract Tests 证明 snapshot isolation，不为了产生生产 commit 而改 Runtime。
10. Phase 3.3 统一 lifecycle / test / review History Contract，并保持序列化兼容。
11. 新增 Context 字段必须先建立 Contract Test，再进行最小 Runtime 修改。
12. Context Access Policy 必须通过 role-specific projection 实现，不能让 Agent 依赖 `to_dict()` 的序列化字段存在性。
13. Runtime projection 与 persistence serialization 必须保持职责分离。
14. Read-only execution context 优先通过 snapshot isolation + Contract Tests 建立所有权边界，不急于引入复杂 immutable abstraction。
15. Legacy `Task.context` 退出必须先定义兼容边界，再逐步清除非必要读取点，不能一次性删除导致隐式依赖回归。
16. Canonical runtime state 必须优先于 legacy compatibility data；compatibility bridge 只能补充不能覆盖 canonical fields。
17. Legacy usage inventory 必须成为 Contract Test，防止未来 runtime 修改重新扩大 `Task.context` 读取面。
18. LLM abstraction 先冻结最小 provider-independent contract，再引入 deterministic MockLLM，避免 Agent / Workflow 在 provider 细节上继续耦合。
19. MockLLM 必须零网络、可重复、可记录调用，才能成为后续 Agent / Workflow integration tests 的稳定基础。

---

# 当前下一动作

**4.2 MockLLM Contract 验收**

执行路径：

```text
BaseLLM
   ↓
MockLLM
   ├── deterministic response
   ├── FIFO response queue
   ├── invocation recording
   └── type / contract validation
        ↓
Agent integration tests
```

用户完成 `tests/test_mock_llm.py` 专项测试及全量 `pytest -q` 后，再进入 **4.3 Agent → BaseLLM**。
