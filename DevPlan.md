# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 6 — Workflow / Project Orchestrator**

最新用户验收基线：

```text
pytest -q
557 passed in 1.34s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6.1 TaskWorkflow 状态机已完成。Phase 6.2 Dependency-aware Scheduler 已完成。Phase 6.3 ProjectOrchestrator 已完成。Phase 6.4 Task 并行执行已完成，下一节点为 6.5 Retry / Resume。**

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

### <span style="color:green">√</span> 6.4.3 Concurrency hardening

已完成 TaskManager 并发安全边界：

1. `TaskManager` lifecycle mutation 使用 `RLock` 保护 validate → history → status mutation 原子区间；
2. 同一 Task 的并发 transition 至多一次成功，避免重复 lifecycle transition；
3. 不同 Task 的 status/history/result/error 在并发执行下保持隔离；
4. concurrent scheduler/read operations 不破坏 TaskManager 状态一致性；
5. 非法并发 transition 不污染 `status_history`；
6. 使用 re-entrant lock 支持嵌套 lifecycle 调用且避免死锁；
7. 新增 `tests/test_task_manager_concurrency.py`，覆盖上述 concurrency safety contracts；
8. 不在本阶段引入 retry/resume/persistence，保持职责边界稳定。

用户最终验收：

```text
pytest tests/test_task_manager_concurrency.py -q
6 passed in 0.05s

pytest -q
557 passed in 1.34s
```

**结论：6.4 Task 并行执行已完成。**

## ☐ 6.5 Retry / Resume

下一阶段重点：

1. 明确 Task failure 后 retry 的状态机边界；
2. 区分 retry attempt、workflow stage 与 Task lifecycle status；
3. retry 必须保持已有成功 peer 的结果不受影响；
4. 明确 retryable / non-retryable failure contract；
5. 建立最大 retry 次数、attempt history 与最终失败语义；
6. Resume 只恢复可恢复的 Task execution state，不在本阶段引入完整 persistence；
7. 确保 retry/resume 与 dependency scheduler、TaskWorkflow、TaskManager 的职责边界清晰；
8. 优先 contract tests，再实现最小状态机变化。

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

**当前节点：Phase 6.5 Retry / Resume。**

1. 6.4.3 Concurrency hardening 已通过专项与全量回归并正式完成。
2. 下一步先建立 retry/resume contract tests，不直接扩大实现范围。
3. 优先冻结 retry attempt、最大次数、失败分类与 Task 状态转换语义。
4. Resume 暂不依赖持久化层，只定义内存态恢复边界。
5. 完成后运行专项测试与全量 `pytest -q`。
6. 全量通过后标记 6.5 完成，再进入 **6.6 ProjectResult**。
