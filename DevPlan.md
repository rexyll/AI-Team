# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 6 — Workflow / Project Orchestrator**

最新用户验收基线：

```text
pytest -q
542 passed in 1.08s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6.1 TaskWorkflow 状态机已完成。Phase 6.2 Dependency-aware Scheduler 已完成。Phase 6.3 ProjectOrchestrator 已完成。**

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

Phase 4 已完成，既有详细记录保留于 Git 历史。

# Phase 5 — Tool / Sandbox Architecture

## <span style="color:green">√</span> 5.1 Tool Contract
## <span style="color:green">√</span> 5.2 Tool Registry Contract
## <span style="color:green">√</span> 5.3 Tool Argument Validation
## <span style="color:green">√</span> 5.4 Workspace Sandbox
## <span style="color:green">√</span> 5.5 Tool Permission Policy
## <span style="color:green">√</span> 5.6 Tool Error Contract

**结论：Phase 5 Tool / Sandbox Architecture 已完成。详细契约记录保留于 Git 历史。**

# Phase 6 — Workflow / Project Orchestrator

## <span style="color:green">√</span> 6.1 TaskWorkflow 状态机

### <span style="color:green">√</span> 6.1.1 Stage execution → state transition contract

已完成 declarative stage transition contract，并冻结 stage outcome、source/target topology 与 `TaskManager.transition()` mutation boundary。

### <span style="color:green">√</span> 6.1.2 TaskWorkflow → transition contract integration

已完成 implementation convergence：Developer / Tester / Reviewer outcome 统一映射到 declarative transition contract，实际状态 mutation 仍统一经过 `TaskManager.transition()`。

**结论：6.1 TaskWorkflow 状态机已完成。**

## <span style="color:green">√</span> 6.2 Dependency-aware Scheduler

### <span style="color:green">√</span> 6.2.1 Dependency Scheduler read-only contract

已建立 dependency-aware decision contract：ready、blocked、unknown dependency、cycle detection，以及 read-only scheduler boundary。

### <span style="color:green">√</span> 6.2.2 Orchestrator readiness boundary convergence

已完成 Core Orchestrator 与 Scheduler 的职责收敛：DependencyScheduler 成为 readiness decision source，TaskManager 仍是唯一 lifecycle mutation boundary。

用户此前全量验收：

```text
pytest -q
533 passed in 1.11s
```

**结论：6.2 Dependency-aware Scheduler 已完成。**

## <span style="color:green">√</span> 6.3 ProjectOrchestrator

已完成 project-level execution facade，并完成 `ProjectOrchestrator` 与底层 `Orchestrator` 的职责收敛。

当前正式生命周期：

```text
Requirement
    ↓
PlannerAgent
    ↓
validated Plan
    ↓
PlanBuilder
    ↓
TaskManager
    ↓
core.Orchestrator
    ↓
ProjectResult
```

本节点冻结以下边界：

1. `ProjectOrchestrator` 负责 project-level facade：plan → task graph → execution → project result。
2. `core.Orchestrator` 只负责执行已经构建好的 `TaskManager`，不重复承担 project planning。
3. `DependencyScheduler` 继续负责 dependency readiness decision。
4. `TaskWorkflow` 继续负责单 Task stage lifecycle 与 transition contract。
5. `TaskManager` 仍是唯一实际 Task lifecycle mutation boundary。
6. `ProjectOrchestrator.run(requirement)` 正式返回 `ProjectResult`，不再返回 `TaskManager`。
7. `ProjectOrchestrator.last_task_manager` 保留实际执行图访问边界；`last_plan` 与 `last_result` 分别记录 project plan 与最终 result。
8. `ProjectResult` 为 provider-independent、immutable 的 project execution summary。
9. Planner 输出在进入 `PlanBuilder` 前必须经过 `validate_plan()`。
10. 本节点不引入 Task 并行执行、retry/resume 或 persistence。

本节点通过用户最终回归：

```text
pytest -q
542 passed in 1.08s
```

**结论：6.3 ProjectOrchestrator 已完成。**

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

---

# 当前下一动作

**当前节点：Phase 6.4 Task 并行执行。**

1. 用户 Pull 最新提交。
2. 运行 `pytest tests/test_project_orchestrator.py tests/test_project_execution.py -q`，确认 6.3 project facade contract。
3. 运行 `pytest tests/test_orchestrator_scheduler_contract.py tests/test_dependency_scheduler.py tests/test_workflow_transition_integration.py tests/test_workflow_stage_transition_contract.py tests/test_workflow_state_machine_contract.py -q`，确认 6.1 / 6.2 / 6.3 回归稳定。
4. 运行 `pytest -q`，建立新的全量基线。
5. 下一阶段进入 **6.4 Task 并行执行**：在现有 DependencyScheduler execution layers 基础上设计并发边界。
6. 并行执行必须保持 `TaskManager` 为唯一 lifecycle mutation boundary，并禁止 Scheduler 直接修改 Task。
7. 明确 worker isolation、最大并发度、ready-layer 批次语义以及 failure/blocked propagation 的 contract。
8. 本阶段暂不引入 retry/resume、persistence；ProjectResult 继续作为既有 project-level summary contract 使用。
