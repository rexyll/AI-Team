# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 7 — Persistence / Observability**

最新用户验收基线：

```text
pytest -q
602 passed in 1.37s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6 Workflow / Project Orchestrator 已完成。当前进入 Phase 7 Persistence / Observability。**

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

已完成 declarative stage transition contract，并冻结 stage outcome、source/target topology 与 `TaskManager.transition()` mutation boundary。

**结论：6.1 TaskWorkflow 状态机已完成。**

## <span style="color:green">√</span> 6.2 Dependency-aware Scheduler
### <span style="color:green">√</span> 6.2.1 Dependency Scheduler read-only contract
### <span style="color:green">√</span> 6.2.2 Orchestrator readiness boundary convergence

已完成 dependency-aware decision contract 与 Orchestrator readiness boundary convergence：DependencyScheduler 成为 readiness decision source，TaskManager 仍是唯一 lifecycle mutation boundary。

**结论：6.2 Dependency-aware Scheduler 已完成。**

## <span style="color:green">√</span> 6.3 ProjectOrchestrator

已完成 project-level execution facade，并冻结以下边界：

1. `ProjectOrchestrator` 负责 requirement → plan → task graph → execution → `ProjectResult`。
2. `core.Orchestrator` 只负责执行已经构建好的 `TaskManager`。
3. `DependencyScheduler` 负责 dependency readiness decision。
4. `TaskWorkflow` 负责单 Task stage lifecycle。
5. `TaskManager` 仍是唯一实际 Task lifecycle mutation boundary。
6. `ProjectOrchestrator.run(requirement)` 返回 immutable `ProjectResult`。
7. `last_task_manager`、`last_plan`、`last_result` 分别保存执行图、plan 与最终结果。
8. Planner 输出进入 `PlanBuilder` 前必须经过 `validate_plan()`。
9. ProjectResult 为 provider-independent project execution summary。

**结论：6.3 ProjectOrchestrator 已完成。**

## <span style="color:green">√</span> 6.4 Task 并行执行
### <span style="color:green">√</span> 6.4.1 Task layer executor contract
### <span style="color:green">√</span> 6.4.2 Layer-based Orchestrator integration
### <span style="color:green">√</span> 6.4.3 Concurrency hardening

已完成 bounded layer executor、DependencyScheduler layer integration 与 TaskManager 并发安全边界。并发层只保证 layer readiness，不假设 worker 实际进入 Agent 的先后顺序；同层独立 Task 可并行执行，依赖下游只能在上游 layer 完成后进入下一轮 scheduling。

**结论：6.4 Task 并行执行已完成。**

## <span style="color:green">√</span> 6.5 Retry / Resume

### <span style="color:green">√</span> 6.5.1 Retry lifecycle contract
### <span style="color:green">√</span> 6.5.2 Retry policy integration
### <span style="color:green">√</span> 6.5.3 Resume in-memory execution boundary
### <span style="color:green">√</span> 6.5.4 Retry / Resume integration

Retry / Resume 已完成，保持不重新 Planner、不重建 Task Graph 的 execution-state continuation boundary。TaskManager 是唯一 retry/lifecycle mutation boundary；DependencyScheduler 继续负责 readiness decision；持久化恢复保留给 Phase 7.6。

**结论：6.5 Retry / Resume 已完成。**

## <span style="color:green">√</span> 6.6 ProjectResult

已完成 project-level immutable execution summary contract，并通过用户全量回归：

1. `ProjectResult` 为 immutable value object；
2. 成功、失败、阻塞、incomplete 结果语义明确；
3. 汇总 total/completed/failed/blocked task 数量；
4. failed / blocked Task ID 稳定、可序列化；
5. `to_dict()` 返回 JSON-friendly representation；
6. ProjectResult 不持有可变 TaskManager / Agent / Provider 引用；
7. `ProjectOrchestrator.run()` / `resume()` 统一返回 ProjectResult；
8. 空 TaskManager、部分完成、失败、阻塞等边界状态有明确 contract tests。

用户最终验收：

```text
pytest tests/test_project_result_contract.py -q
8 passed in 0.03s

pytest -q
602 passed in 1.37s
```

**结论：Phase 6 Workflow / Project Orchestrator 已完成。**

# Phase 7 — Persistence / Observability

## ☐ 7.1 Task persistence
## ☐ 7.2 Project persistence
## ☐ 7.3 Agent execution records
## ☐ 7.4 Tool execution logs
## ☐ 7.5 Workflow event log
## ☐ 7.6 Resume from persisted state

### Phase 7 开发边界

Phase 7 的目标不是立即引入数据库，而是先建立稳定的 persistence / observability contracts，再选择具体存储实现。

优先顺序：

1. 先冻结 Task persistence schema 与 serialization contract；
2. 再冻结 Project persistence schema；
3. 再记录 Agent / Tool / Workflow execution events；
4. 最后把 persisted state 接入 `ProjectOrchestrator.resume()`；
5. 具体数据库 / 文件存储实现应服从上述 contract，不反向污染 Workflow 核心层。

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

**当前节点：Phase 7.1 Task persistence。**

1. 先新增 `tests/test_task_persistence_contract.py`，冻结 Task serialization / deserialization contract；
2. 明确 persisted Task 不携带 Agent / LLM / runtime object 引用；
3. 明确 status、dependencies、retry state、status history、context snapshot 等生命周期字段的持久化边界；
4. 专项测试通过后再实现 persistence adapter；
5. 最后执行全量 `pytest -q`；
6. 只有用户全量验收通过后，才将 7.1 标记为 √。
