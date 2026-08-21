# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 6 — Workflow / Project Orchestrator**

最新用户验收基线：

```text
pytest -q
578 passed in 1.36s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6.1 TaskWorkflow 状态机已完成。Phase 6.2 Dependency-aware Scheduler 已完成。Phase 6.3 ProjectOrchestrator 已完成。Phase 6.4 Task 并行执行已完成。Phase 6.5 Retry / Resume 正在推进。**

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

### ☐ 6.5.1 Retry lifecycle contract

当前已进入 retry contract hardening：

1. `Task.retry_attempt` 从 0 开始，并与 `status_history` 分离；
2. `Task.max_retries` 必须显式配置，默认预算为 0；
3. retry attempt 只允许由 retryable failure 创建，并受 retry budget 限制；
4. `TaskManager.retry_task()` 只允许从 `FAILED` 状态重新打开 Task；
5. 合法 retry 的生命周期目标固定为 `FAILED → READY`；
6. retry 必须记录 attempt、reason、retryable，并清除旧 error；
7. budget exhausted / non-retryable / invalid source state 的 retry 必须保持 Task 状态、history、error 与 attempt 不变；
8. retry 一个 Task 不得修改其它 peer Task；
9. 已新增 `tests/test_task_manager_retry_contract.py`，等待用户 Pull 后进行专项与全量验证。

### ☐ 6.5.2 Retry policy integration

待 6.5.1 验收后继续：将 retryable / max retry policy 接入 Orchestrator execution failure boundary，避免把 retry decision 混入 Agent、Workflow 或 Scheduler。

### ☐ 6.5.3 Resume in-memory execution boundary

待 6.5.2 验收后继续：定义无 persistence 前提下可恢复 execution state 与 resume entry point；不引入持久化层。

### ☐ 6.5.4 Retry / Resume integration

待前述 contract 冻结后，验证 retry/resume 与 DependencyScheduler、TaskWorkflow、TaskManager 的协作边界。

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

**当前节点：Phase 6.5.1 Retry lifecycle contract。**

1. 用户当前基线为 `578 passed`，作为 6.5.1 开始前回归基线。
2. 已新增 `tests/test_task_manager_retry_contract.py`，冻结 TaskManager retry lifecycle 的最小 contract。
3. 用户 Pull 后先运行：

```text
pytest tests/test_retry_contract.py tests/test_task_manager_retry_contract.py -q
```

4. 再运行全量 `pytest -q`。
5. 若全部通过，下一步实现 6.5.2 Retry policy integration，并在完成后再更新节点为 √。
6. Resume 暂不与 persistence 耦合，保持 Phase 7 的 persistence 边界。
