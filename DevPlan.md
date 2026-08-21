# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 6 — Workflow / Project Orchestrator**

最新用户验收基线：

```text
pytest -q
592 passed in 1.38s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6.1 TaskWorkflow 状态机已完成。Phase 6.2 Dependency-aware Scheduler 已完成。Phase 6.3 ProjectOrchestrator 已完成。Phase 6.4 Task 并行执行已完成。Phase 6.5 Retry / Resume 正在推进，6.5.1 与 6.5.2 已通过用户全量回归，当前进入 6.5.3 Resume in-memory execution boundary 验收。**

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

已完成 bounded layer executor、DependencyScheduler layer integration 与 TaskManager 并发安全边界。TaskManager 是唯一 lifecycle mutation boundary；同层独立 Task 可并行执行，依赖下游只能在上游 layer 完成后进入下一轮 scheduling。

用户最终验收基线：

```text
pytest tests/test_task_manager_concurrency.py -q
6 passed in 0.05s
```

**结论：6.4 Task 并行执行已完成。**

## ☐ 6.5 Retry / Resume

### <span style="color:green">√</span> 6.5.1 Retry lifecycle contract

已完成并通过用户全量回归验证：

1. `Task.retry_attempt` 从 0 开始，并与 `status_history` 分离；
2. `Task.max_retries` 默认预算为 0，并支持显式配置；
3. retry attempt 只允许由 retryable failure 创建，并受 retry budget 限制；
4. `TaskManager.retry_task()` 只允许从 `FAILED` 状态重新打开 Task；
5. 合法 retry 的生命周期目标固定为 `FAILED → READY`；
6. retry 记录 attempt、reason、retryable，并清除旧 error；
7. budget exhausted / non-retryable / invalid source state 的 retry 不污染已有 lifecycle state；
8. retry 一个 Task 不修改其它 peer Task；
9. 新增 retry lifecycle contract tests。

用户验收：

```text
pytest -q
583 passed in 1.36s
```

### <span style="color:green">√</span> 6.5.2 Retry policy integration

已完成 Orchestrator failure boundary integration，并通过用户全量回归：

1. `runtime.retry_policy.decide_retry()` 作为纯 retry decision source；
2. Orchestrator 在 execution failure boundary 统一进行 failure classification 与 retry decision；
3. Agent、TaskWorkflow、DependencyScheduler 不直接承担 retry policy；
4. `TaskManager` 仍是唯一 retry/lifecycle mutation boundary；
5. retryable failure 在预算内通过 `FAILED → READY` 重新进入 scheduler；
6. non-retryable failure 或预算耗尽保持 `FAILED`；
7. 默认 `ValueError` / `TypeError` / `KeyError` 视为 non-retryable，其它未分类执行异常默认为 execution failure；
8. 支持注入 failure classifier，为后续 quality-gate retry 保留扩展点；
9. 新增 `tests/test_orchestrator_retry_policy.py`，覆盖 retryable failure、non-retryable failure、budget exhaustion、custom classifier 与 non-failed task guard。

用户最终验收：

```text
pytest -q
592 passed in 1.38s
```

**结论：6.5.2 Retry policy integration 已完成。**

### ☐ 6.5.3 Resume in-memory execution boundary

当前节点：定义并验收无 persistence 前提下的 in-memory resume execution boundary。

目标：

1. `ProjectOrchestrator.resume()` 从现有 `TaskManager` execution state 继续执行；
2. resume 不重新调用 Planner；
3. resume 不重新构建 Task Graph；
4. 已完成 Task 保持完成状态，不被重复执行；
5. 当前可执行 Task 继续交给 Orchestrator / DependencyScheduler；
6. 没有可恢复 in-memory execution state 时明确拒绝 resume；
7. 不在 Phase 6.5.3 引入 persistence，持久化恢复留给 Phase 7.6。

下一步先运行专项测试：

```text
pytest tests/test_project_resume.py -q
```

专项通过后再运行全量 `pytest -q`。全量通过后将 6.5.3 标记为 √。

### ☐ 6.5.4 Retry / Resume integration

待 6.5.3 contract 冻结后，验证 retry/resume 与 DependencyScheduler、TaskWorkflow、TaskManager 的协作边界。

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

---

# 当前下一动作

**当前节点：Phase 6.5.3 Resume in-memory execution boundary。**

1. 用户已确认 6.5.2 全量回归通过：`592 passed in 1.38s`。
2. Retry policy 已冻结为 pure decision source，failure classification 位于 Orchestrator boundary，TaskManager 独占 retry/lifecycle mutation。
3. 已提供 `ProjectOrchestrator.resume()` 作为 in-memory resume entry point，并保持 resume 不重新规划、不重建 task graph。
4. 用户 Pull 后先运行：

```text
pytest tests/test_project_resume.py -q
```

5. 再运行全量 `pytest -q`。
6. 全量通过后标记 6.5.3 为 √，然后进入 **6.5.4 Retry / Resume integration**。
7. Resume 暂不与 persistence 耦合，Phase 7.6 再处理 persisted state resume。
