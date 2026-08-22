# AI-Team DevPlan

> 当前开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 7 — Persistence / Observability**

最新用户验收基线：

```text
pytest -q
775 passed in 2.16s
```

7.5.4 Audit Consistency 专项节点已通过用户验收，当前进入 **7.5.5 Execution-history dedup / conflict semantics**。

Phase 3 Context Lifecycle Governance、Phase 4 LLM Abstraction、Phase 5 Tool / Sandbox Architecture、Phase 6 Workflow / Project Orchestrator 均已完成。

Phase 7.1 / 7.1.1 / 7.2 / 7.3 / 7.4 / 7.5.1 / 7.5.2 / 7.5.3 / 7.5.4 已完成。

---

# Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.4.6 Legacy dependency bridge isolation

**Phase 3 Context Lifecycle Governance 已完成。**

# Phase 4 — LLM Abstraction

## <span style="color:green">√</span> 4.1 BaseLLM Contract
## <span style="color:green">√</span> 4.2 MockLLM
## <span style="color:green">√</span> 4.3.1 ProviderLLM adapter contract
## <span style="color:green">√</span> 4.3.2 Agent LLM injection
## <span style="color:green">√</span> 4.4 Workflow → LLM-independent
## <span style="color:green">√</span> 4.5 Provider/config 可替换

**Phase 4 已完成。**

# Phase 5 — Tool / Sandbox Architecture

## <span style="color:green">√</span> 5.1 Tool Contract
## <span style="color:green">√</span> 5.2 Tool Registry Contract
## <span style="color:green">√</span> 5.3 Tool Argument Validation
## <span style="color:green">√</span> 5.4 Workspace Sandbox
## <span style="color:green">√</span> 5.5 Tool Permission Policy
## <span style="color:green">√</span> 5.6 Tool Error Contract

**Phase 5 已完成。**

# Phase 6 — Workflow / Project Orchestrator

## <span style="color:green">√</span> 6.1 TaskWorkflow 状态机
### <span style="color:green">√</span> 6.1.1 Stage execution → state transition contract
### <span style="color:green">√</span> 6.1.2 TaskWorkflow → transition contract integration
## <span style="color:green">√</span> 6.2 Dependency-aware Scheduler
### <span style="color:green">√</span> 6.2.1 Dependency Scheduler read-only contract
### <span style="color:green">√</span> 6.2.2 Orchestrator readiness boundary convergence
## <span style="color:green">√</span> 6.3 ProjectOrchestrator
## <span style="color:green">√</span> 6.4 Task 并行执行
### <span style="color:green">√</span> 6.4.1 Task layer executor contract
### <span style="color:green">√</span> 6.4.2 Layer-based Orchestrator integration
### <span style="color:green">√</span> 6.4.3 Concurrency hardening
## <span style="color:green">√</span> 6.5 Retry / Resume
### <span style="color:green">√</span> 6.5.1 Retry lifecycle contract
### <span style="color:green">√</span> 6.5.2 Retry policy integration
### <span style="color:green">√</span> 6.5.3 Resume in-memory execution boundary
### <span style="color:green">√</span> 6.5.4 Retry / Resume integration
## <span style="color:green">√</span> 6.6 ProjectResult

**Phase 6 已完成。**

# Phase 7 — Persistence / Observability

## <span style="color:green">√</span> 7.1 Task persistence contract
## <span style="color:green">√</span> 7.1.1 Task persistence adapter
## <span style="color:green">√</span> 7.2 Project persistence
## <span style="color:green">√</span> 7.3 Agent execution records

## <span style="color:green">√</span> 7.4 Project Resume / Recovery
### <span style="color:green">√</span> 7.4.1 Persisted project resume contract
### <span style="color:green">√</span> 7.4.2 ProjectOrchestrator persisted resume integration
### <span style="color:green">√</span> 7.4.3 Recovery consistency / corruption boundaries

已完成 persisted project → runtime state 恢复边界、Planner-free continuation、TaskManager identity consistency、ProjectResult consistency，以及 corrupt snapshot / identity mismatch / unknown task tool-history 等恢复边界。

## <span style="color:green">√</span> 7.5 Tool execution logs
### <span style="color:green">√</span> 7.5.1 Tool log ownership / persistence contract
### <span style="color:green">√</span> 7.5.2 Project recovery tool-log integration
### <span style="color:green">√</span> 7.5.3 Audit / query observability boundary
### <span style="color:green">√</span> 7.5.4 Cross-boundary Audit Consistency

7.5.4 已完成：`audit_consistency()` 对 persisted canonical history 与 task-local history 进行只读比较，区分缺失记录、额外记录与相同 `execution_id` 的 payload 冲突；Project persistence / orchestrator 提供只读 consistency API，且不改变 canonical ownership。

用户验收基线：

```text
pytest -q
775 passed in 2.16s
```

### <span style="color:orange">▶</span> 7.5.5 Execution-history dedup / conflict semantics

本节点目标：

1. 统一 `execution_id` 作为 immutable execution record 的唯一身份键；
2. 相同 `execution_id` + 完全相同 payload 视为幂等重复，不产生第二条记录；
3. 相同 `execution_id` + 任意 payload 差异统一视为 conflict，并使用统一的 `ToolExecutionConflictError`；
4. `ToolExecutionHistory.from_dict()`、`merge()`、`append_if_absent()` 使用同一去重 / 冲突语义；
5. `ToolExecutionPersistenceAdapter.save_if_absent*()` 使用与内存 history 相同的 conflict 语义；
6. project recovery 从 task-local history 重建时复用同一规则，避免 persistence / recovery / audit 出现不同判定；
7. 冲突必须在写入前被发现，merge / batch persistence 不得留下部分更新。

专项测试通过后执行全量 `pytest -q`，用户验收后标记 7.5.5，再进入 7.5.6。

## ☐ 7.5.6 Persistence atomic batch semantics

目标：把多项 runtime observability 更新收敛为单一可恢复事务边界，验证失败时不得留下半更新 snapshot。

## ☐ 7.6 Workflow event log

### Phase 7 开发边界

Phase 7 的目标不是立即引入数据库，而是先建立稳定的 persistence / observability contracts，再选择具体存储实现。

优先顺序：

1. Task persistence schema / serialization contract；
2. Task persistence adapter；
3. Project persistence schema / adapter；
4. Agent execution records / execution history；
5. persisted state 接入 `ProjectOrchestrator.resume()`；
6. Tool / Workflow observability；
7. 具体数据库 / 文件存储实现必须服从上述 contract，不反向污染 Workflow 核心层。

# Phase 8 — Production Hardening

## ☐ 8.1 Contract Tests
## ☐ 8.2 Failure Injection Tests
## ☐ 8.3 Security Tests
## ☐ 8.4 LLM Mock Integration Tests
## ☐ 8.5 Long-running Workflow Tests
## ☐ 8.6 Performance / Concurrency Tests
## ☐ 8.7 Documentation / Examples

---

# 当前下一动作

**当前节点：7.5.5 Execution-history dedup / conflict semantics。**

1. 专项测试 `tests/test_tool_execution_history_dedup_contract.py`；
2. 通过后执行全量 `pytest -q`；
3. 用户验收并记录最终 SHA；
4. 标记 7.5.5 完成后进入 7.5.6 Persistence atomic batch semantics。
