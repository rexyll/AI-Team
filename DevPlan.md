# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 5 — Tool / Sandbox Architecture**

最新用户验收：

```text
pytest -q
477 passed in 10.28s
```

**Phase 4.5 Provider/config 可替换、Phase 5.1 Tool Contract、Phase 5.2 Tool Registry、Phase 5.3 Tool Argument Validation 已完成。当前进入 5.4 Workspace Sandbox。**

工作树：5.3 已完成实现并通过用户全量验收；5.4 已开始，已建立 WorkspaceSandbox 最小安全边界与专项 contract tests，等待用户 Pull 后验证。

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

相关提交：

```text
8872b45  feat: add schema-based tool argument validation
 da65b8f  refactor: enforce tool schema validation before execution
 5f83d29  test: define Tool argument validation contract
```

**结论：5.3 Tool Argument Validation 已完成。**

## ☐ 5.4 Workspace Sandbox

已开始建立统一 `WorkspaceSandbox` filesystem boundary。

本节点当前设计目标：

1. 所有 Tool filesystem path resolution 统一经过 workspace boundary。
2. relative path 与 absolute path 都必须经过 containment check。
3. `..` traversal 必须拒绝。
4. symlink resolve 后逃逸 workspace 必须拒绝。
5. 非 path 类型必须明确拒绝。
6. file / directory 的基础类型边界提供统一 helper。
7. 保留现有 `resolve_workspace_path()` 兼容 API，逐步迁移调用方。
8. 本节点暂不引入 Tool permission policy；权限语义留给 5.5。

已新增：

```text
tests/test_workspace_sandbox.py
```

已实现：

```text
security.workspace.WorkspaceSandbox
security.workspace.DEFAULT_SANDBOX
```

当前提交：

```text
10e1228  feat: introduce WorkspaceSandbox boundary
5c60f5d  test: define WorkspaceSandbox security contract
```

**下一步：用户 Pull 后运行 WorkspaceSandbox 专项测试及全量 pytest；验证通过后完成 5.4，再进入 5.5 Tool Permission Policy。**

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

---

# 当前下一动作

**当前节点：Phase 5.4 Workspace Sandbox。**

1. 用户 Pull 最新提交。
2. 运行 `pytest tests/test_workspace_sandbox.py -q`。
3. 运行全量 `pytest -q`。
4. 用户验收通过后，将 5.4 标记完成。
5. 下一节点进入 5.5 Tool Permission Policy。
