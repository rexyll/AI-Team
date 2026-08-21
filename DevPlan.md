# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 6 — Workflow / Project Orchestrator**

最新用户验收基线：

```text
pytest -q
551 passed in 1.34s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6.1 TaskWorkflow 状态机已完成。Phase 6.2 Dependency-aware Scheduler 已完成。Phase 6.3 ProjectOrchestrator 已完成。Phase 6.4.1 / 6.4.2 Task 并行执行基础架构已完成，下一节点为 6.4.3 Concurrency hardening。**

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

用户验收基线：

```text
pytest -q
542 passed in 1.08s
```

**结论：6.3 ProjectOrchestrator 已完成。**

## <span style="color:green">√</span> 6.4 Task 并行执行

### <span style="color:green">√</span> 6.4.1 Task layer executor contract

已完成 `runtime.task_executor.TaskLayerExecutor`：

1. bounded worker pool，默认 `max_workers=4`；
2. 输入 task 顺序与返回结果顺序保持一致；
3. 一个 worker 失败不会主动取消其它 peer；
4. 所有 submitted futures 完成后才向调用方传播第一个异常；
5. executor 不读取/修改 Task lifecycle 状态；
6. invalid worker count、invalid task、invalid callable 均在 executor boundary 拒绝。

### <span style="color:green">√</span> 6.4.2 Layer-based Orchestrator integration

已完成 `core.Orchestrator` 的 layer-based execution：

1. `DependencyScheduler` 产出的 ready batch 作为当前 execution layer；
2. 同一 layer 内的独立 Task 通过 `TaskLayerExecutor` 并发执行；
3. 当前 layer 的所有 worker 完成后才重新运行 dependency scheduling；
4. 因此存在依赖关系的下游 Task 不会与其上游 Task 同层执行；
5. worker failure 由 `_execute_task()` 转换为对应 Task 的 failed 状态，不取消其它独立 peer；
6. 失败 Task 的下游依赖在下一轮 scheduler 中进入 blocked propagation；
7. Developer workflow 在每个 Task execution 内独立创建 `TaskWorkflow`，避免共享 workflow 实例状态；
8. `TaskManager` 仍是 lifecycle mutation boundary，Scheduler 与 Executor 均不直接改变 lifecycle。

本阶段用户最终回归：

```text
pytest -q
551 passed in 1.34s
```

**结论：6.4.1 / 6.4.2 已完成。**

### ☐ 6.4.3 Concurrency hardening（当前节点）

下一阶段重点：

1. 明确 `TaskManager` 在并发 worker 环境下的 mutation / read consistency；
2. 增加 concurrent lifecycle mutation regression tests；
3. 验证同一 Task 不会被重复执行或发生非法双重 transition；
4. 验证不同 Task 的 history/result/error 不会串写；
5. 增加 worker exception、slow peer、mixed success/failure 的 deterministic contract；
6. 建立轻量 concurrency performance contract，但不以 benchmark 数值作为业务正确性依据；
7. 不引入 retry/resume、persistence 等跨阶段功能。

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

**当前节点：Phase 6.4.3 Concurrency hardening。**

1. 用户已完成全量回归：`551 passed`。
2. 下一步增加 TaskManager concurrency safety contract，而不是继续扩大业务功能面。
3. 优先测试 lifecycle transition、result/error/history 的隔离性与 deterministic semantics。
4. 完成后运行相关专项测试与全量 `pytest -q`。
5. 全量通过后，将 6.4.3 标记完成，再进入 **6.5 Retry / Resume**。
6. Retry / Resume 之前不引入 persistence，避免两个状态恢复机制同时演进。
