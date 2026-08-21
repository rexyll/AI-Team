# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 6 — Workflow / Project Orchestrator**

最新用户验收基线：

```text
pytest -q
525 passed in 1.10s
```

**Phase 5 Tool / Sandbox Architecture 已完成。Phase 6.1 TaskWorkflow 状态机已完成。Phase 6.2 Dependency-aware Scheduler 已启动。**

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

已完成现有 Tool 能力的最小 provider-independent contract 冻结，并新增 `tests/test_tool_contract.py`。

## <span style="color:green">√</span> 5.2 Tool Registry Contract

已完成 Registry abstraction，并通过用户 Pull 后专项测试与全量验收。

## <span style="color:green">√</span> 5.3 Tool Argument Validation

已完成 schema-aware Tool 参数校验，并通过用户最终全量验收：

```text
pytest -q
477 passed in 10.28s
```

本节点冻结以下边界：

1. Tool arguments 必须是 JSON object。
2. `required` 参数缺失必须拒绝。
3. unknown arguments 必须拒绝，不能静默吞掉。
4. 已声明的 JSON primitive/container 类型必须校验。
5. malformed schema 必须拒绝执行。
6. validation 失败时 Tool 不得执行。
7. 使用统一 `ToolArgumentValidationError` 表达参数/schema validation failure。
8. Developer tool-calling loop 在 Tool execution 前执行 schema validation。
9. 保留旧 `validate_tool_arguments(tool, arguments)` 两参数兼容行为，避免破坏 legacy boundary。
10. 不把 provider-specific LLM configuration 引入 Tool validation。

**结论：5.3 Tool Argument Validation 已完成。**

## <span style="color:green">√</span> 5.4 Workspace Sandbox

已建立统一 `WorkspaceSandbox` filesystem boundary，并通过用户最终验收：

```text
pytest tests/test_workspace_sandbox.py -q
9 passed in 0.06s

pytest -q
486 passed in 1.11s
```

本节点冻结以下边界：

1. 所有 Tool filesystem path resolution 统一经过 workspace boundary。
2. relative path 与 absolute path 都必须经过 containment check。
3. `..` traversal 必须拒绝。
4. symlink resolve 后逃逸 workspace 必须拒绝。
5. 非 path 类型必须明确拒绝。
6. file / directory 的基础类型边界提供统一 helper。
7. 保留现有 `resolve_workspace_path()` 兼容 API，逐步迁移调用方。
8. 本节点不引入 Tool permission policy；权限语义进入 5.5。

**结论：5.4 Workspace Sandbox 已完成。**

## <span style="color:green">√</span> 5.5 Tool Permission Policy

已在 Workspace Sandbox 与 Tool Argument Validation 之上建立独立 capability authorization boundary，并通过用户最终验收：

```text
pytest tests/test_tool_permission.py -q
7 passed in 0.03s

pytest -q
493 passed in 1.12s
```

本节点冻结以下边界：

1. deny-by-default；未声明 capability 的 Tool 不得执行对应操作。
2. capability 最小集合为 `read`、`write`、`execute`。
3. Tool identity 与 permission policy 解耦，权限规则不硬编码进具体 Tool。
4. permission policy 不绕过 `WorkspaceSandbox`；路径 containment 仍由 sandbox 负责。
5. permission failure 使用独立 `ToolPermissionError`，不与 argument validation / sandbox error 混淆。
6. policy evaluation 必须发生在 Tool 实际执行前。
7. 当前只实现最小显式 allowlist，不引入复杂 RBAC。
8. `ToolPermissionPolicy` 与 `DEFAULT_TOOL_PERMISSION_POLICY` 提供稳定的后续扩展边界。

**结论：5.5 Tool Permission Policy 已完成。**

## <span style="color:green">√</span> 5.6 Tool Error Contract

已冻结统一 Tool failure/result contract，并通过用户最终验收：

```text
pytest tests/test_tool_error_contract.py -q
8 passed in 0.04s

pytest -q
501 passed in 1.12s
```

已实现：

```text
runtime/tool_errors.py
runtime/tool_result.py
tests/test_tool_error_contract.py
```

本节点冻结以下边界：

1. `ToolError` 提供稳定的 `code/category/message/details` machine-readable contract。
2. `ToolResult` 统一表达成功与失败，成功不得携带 error，失败必须携带 error。
3. 参数校验 → `TOOL_ARGUMENT_INVALID`。
4. 权限拒绝 → `TOOL_PERMISSION_DENIED`。
5. workspace containment violation → `TOOL_SANDBOX_VIOLATION`。
6. timeout → `TOOL_TIMEOUT`。
7. Tool runtime failure → `TOOL_EXECUTION_FAILED`。
8. 未知异常不直接暴露底层异常文本、traceback 或内部环境信息。
9. `ToolResult.to_dict()` 提供 provider-independent JSON-friendly representation。
10. 5.6 不引入 retry/resume；该语义留给 Phase 6.5。

**结论：Phase 5 Tool / Sandbox Architecture 已完成。**

# Phase 6 — Workflow / Project Orchestrator

## <span style="color:green">√</span> 6.1 TaskWorkflow 状态机

### <span style="color:green">√</span> 6.1.1 Stage execution → state transition contract

已完成 declarative stage transition contract：

```text
runtime/workflow_transition.py
tests/test_workflow_stage_transition_contract.py
```

当前契约明确冻结：

| Stage | Outcome | Source | Target |
|---|---|---|---|
| Developer | success | `running` | `review_pending` |
| Developer | execution / invalid result | `running` | `failed` |
| Tester | success | `review_pending` | `reviewing` |
| Tester | quality-gate failure | `review_pending` | `running` |
| Tester | execution / invalid result | `review_pending` | `failed` |
| Reviewer | success / approved | `reviewing` | `completed` |
| Reviewer | quality-gate failure / revision | `reviewing` | `running` |
| Reviewer | execution / invalid result | `reviewing` | `failed` |

本节点特别冻结：

1. stage outcome 与 lifecycle target 必须是一一明确的 contract。
2. transition source 也属于 contract，不能仅根据当前代码“碰巧可转移”推断。
3. review-round limit 属于 Workflow policy，不进入基础 transition topology。
4. scheduler / parallelism / retry / resume 均不属于本节点。
5. `TaskManager.transition()` 仍是唯一实际 status mutation boundary。

**状态：6.1.1 完成。**

### <span style="color:green">√</span> 6.1.2 TaskWorkflow → transition contract integration

已完成 implementation convergence，并通过用户最终全量验收：

```text
pytest -q
525 passed in 1.10s
```

本节点完成：

1. Developer / Tester / Reviewer outcome 都先映射为 `WorkflowOutcomeKind`。
2. lifecycle target 从 `runtime/workflow_transition.py` 的 declarative contract 获取。
3. `TaskWorkflow` 不再重复维护 stage target-state topology。
4. 实际状态 mutation 仍统一经过 `TaskManager.transition()`。
5. integration tests 验证 `status_history` 的 `from/to` 与 declarative transition contract 一致。
6. review-round limit 继续保持在 Workflow policy 层，不污染基础 transition topology。
7. 不引入 scheduler、parallelism、retry/resume 或 persistence 语义。

**结论：6.1 TaskWorkflow 状态机已完成。**

## <span style="color:green">◐</span> 6.2 Dependency-aware Scheduler

本节点已启动，第一步建立只读 Dependency Scheduler contract：

```text
runtime/dependency_scheduler.py
tests/test_dependency_scheduler.py
```

当前冻结的第一层边界：

1. Scheduler 负责 dependency-aware **decision**，不负责 Task lifecycle mutation。
2. `TaskManager.transition()` 继续保持唯一 status mutation boundary。
3. pending/ready task 只有在全部 dependencies 为 `completed` 时才可进入 runnable 集合。
4. failed / blocked dependency 会产生 blocked decision，但 Scheduler 不直接把 Task 改为 `blocked`。
5. unknown dependency 与 dependency cycle 在 Scheduler 初始化时拒绝。
6. execution layers 复用现有 `runtime/dependency_graph.py`，保持 deterministic dependency order。
7. Scheduler 必须是 read-only，不修改 `status`、`status_history`、`error`。
8. 当前不引入并发执行、retry、resume 或 persistence。

下一步将通过专项测试确认该 contract，然后把 Scheduler 作为 `ProjectOrchestrator` 的决策组件接入，而不是把 scheduler 逻辑继续堆进 `TaskManager.get_ready_tasks()`。

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

---

# 当前下一动作

**当前节点：Phase 6.2 Dependency-aware Scheduler。**

1. 用户 Pull 最新提交。
2. 运行 `pytest tests/test_dependency_scheduler.py -q`，确认 Scheduler 第一层 contract。
3. 运行 `pytest tests/test_workflow_transition_integration.py tests/test_workflow_stage_transition_contract.py tests/test_workflow_state_machine_contract.py -q`，确保 6.1 回归稳定。
4. 运行 `pytest -q`，建立新的全量基线。
5. 下一小步：评估并收敛 `TaskManager.get_ready_tasks()` 与 `DependencyScheduler` 的职责边界，避免 dependency readiness 出现双份事实源。
6. 在不改变 `TaskManager.transition()` 唯一 mutation boundary 的前提下，为 ProjectOrchestrator 准备 scheduler-facing API。
7. 本阶段暂不引入并发、retry/resume、persistence。
