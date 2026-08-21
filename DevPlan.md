# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 7 — Persistence / Observability**

最新用户验收基线：

```text
pytest -q
606 passed in 1.35s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6 Workflow / Project Orchestrator 已完成。当前 Phase 7.1 Task persistence contract 已完成，下一步进入 Task persistence adapter。**

---

# Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.4.6 Legacy dependency bridge isolation

已将 Legacy dependency compatibility 收敛到独立 `LegacyDependencyBridge`，canonical completed dependency snapshot 优先，legacy fallback 仅作为兼容路径，并保持 `AgentContext.dependency_context` 稳定接口。

**Phase 3 Context Lifecycle Governance 已完成。**

---

# Phase 4 — LLM Abstraction

## <span style="color:green">√</span> 4.1 BaseLLM Contract
## <span style="color:green">√</span> 4.2 MockLLM
## <span style="color:green">√</span> 4.3.1 ProviderLLM adapter contract
## <span style="color:green">√</span> 4.3.2 Agent LLM injection
## <span style="color:green">√</span> 4.4 Workflow → LLM-independent
## <span style="color:green">√</span> 4.5 Provider/config 可替换

Phase 4 已完成。

# Phase 5 — Tool / Sandbox Architecture

## <span style="color:green">√</span> 5.1 Tool Contract
## <span style="color:green">√</span> 5.2 Tool Registry Contract
## <span style="color:green">√</span> 5.3 Tool Argument Validation
## <span style="color:green">√</span> 5.4 Workspace Sandbox
## <span style="color:green">√</span> 5.5 Tool Permission Policy
## <span style="color:green">√</span> 5.6 Tool Error Contract

**结论：Phase 5 Tool / Sandbox Architecture 已完成。**

# Phase 6 — Workflow / Project Orchestrator

## <span style="color:green">√</span> 6.1 TaskWorkflow 状态机
### <span style="color:green">√</span> 6.1.1 Stage execution → state transition contract
### <span style="color:green">√</span> 6.1.2 TaskWorkflow → transition contract integration

## <span style="color:green">√</span> 6.2 Dependency-aware Scheduler
### <span style="color:green">√</span> 6.2.1 Dependency Scheduler read-only contract
### <span style="color:green">√</span> 6.2.2 Orchestrator readiness boundary convergence

## <span style="color:green">√</span> 6.3 ProjectOrchestrator

已完成 project-level execution facade，并冻结 requirement → plan → task graph → execution → ProjectResult 边界。

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

已完成 immutable project execution summary，并通过用户最终回归：

```text
pytest tests/test_project_result_contract.py -q
8 passed in 0.03s

pytest -q
602 passed in 1.37s
```

**结论：Phase 6 Workflow / Project Orchestrator 已完成。**

# Phase 7 — Persistence / Observability

## <span style="color:green">√</span> 7.1 Task persistence contract

已冻结 Task persistence serialization / deserialization boundary，并完成实现：

1. `Task.to_dict()` 输出 persistence-safe、JSON-friendly mapping；
2. `Task.from_dict()` 支持 lifecycle state round-trip；
3. 缺少 identity 字段时拒绝恢复；
4. status、dependencies、retry state、status history、context、result、review/test state 均保持持久化边界；
5. persisted Task 不携带 Agent、LLM、Router、TaskManager、Workflow 等 runtime object；
6. 恢复后的 Task 继续经过既有 runtime contract validation。

用户最终验收：

```text
pytest -q
606 passed in 1.35s
```

**结论：7.1 Task persistence contract 已完成。**

## ☐ 7.1.1 Task persistence adapter
## ☐ 7.2 Project persistence
## ☐ 7.3 Agent execution records
## ☐ 7.4 Tool execution logs
## ☐ 7.5 Workflow event log
## ☐ 7.6 Resume from persisted state

### Phase 7 开发边界

Phase 7 的目标不是立即引入数据库，而是先建立稳定的 persistence / observability contracts，再选择具体存储实现。

优先顺序：

1. Task persistence schema / serialization contract；
2. Task persistence adapter；
3. Project persistence schema；
4. Agent / Tool / Workflow execution records；
5. persisted state 接入 `ProjectOrchestrator.resume()`；
6. 具体数据库 / 文件存储实现必须服从上述 contract，不反向污染 Workflow 核心层。

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

**当前节点：Phase 7.1.1 Task persistence adapter。**

1. 冻结 adapter 的 save/load/delete/list contract；
2. adapter 只接受 persistence-safe Task representation；
3. 第一版优先使用本地文件存储，避免提前引入数据库依赖；
4. 明确 atomic write、missing Task、corrupt payload、duplicate identity 等错误边界；
5. 专项测试通过后执行全量 `pytest -q`；
6. 用户全量验收通过后再标记 7.1.1 为 √。
