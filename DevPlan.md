# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 5 — Tool / Sandbox Architecture**

最新用户验收：

```text
pytest tests/test_workspace_sandbox.py -q
9 passed in 0.06s

pytest -q
486 passed in 1.11s
```

**Phase 4.5 Provider/config 可替换、Phase 5.1 Tool Contract、Phase 5.2 Tool Registry、Phase 5.3 Tool Argument Validation、Phase 5.4 Workspace Sandbox 已完成。当前进入 5.5 Tool Permission Policy。**

工作树：5.4 已通过用户专项测试与全量验收；下一节点建立 Tool permission policy，并明确 permission 与 path sandbox、argument validation 的职责边界。

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

已实现：

```text
security.workspace.WorkspaceSandbox
security.workspace.DEFAULT_SANDBOX
security.workspace.resolve_workspace_path()
tests/test_workspace_sandbox.py
```

相关提交：

```text
10e1228  feat: introduce WorkspaceSandbox boundary
5c60f5d  test: define WorkspaceSandbox security contract
6ee394b  docs: advance to Phase 5.4 Workspace Sandbox
```

**结论：5.4 Workspace Sandbox 已完成。**

## ☐ 5.5 Tool Permission Policy

目标：在 Workspace Sandbox 的 filesystem containment 之上增加 Tool capability / permission 层，明确“路径合法”与“操作被授权”是两个独立判断。

设计原则：

1. deny-by-default；未声明 capability 的 Tool 不得执行对应操作。
2. permission policy 不绕过 `WorkspaceSandbox`，filesystem path 仍必须经过 sandbox containment。
3. 至少区分 `read`、`write`、`execute` 三类 capability。
4. Tool identity 与 permission policy 解耦，避免把权限规则硬编码进具体 Tool 实现。
5. permission failure 使用独立、稳定的异常契约，不与 argument validation / path containment 混淆。
6. policy evaluation 必须发生在 Tool 实际执行前。
7. policy 应支持最小显式 allowlist，并为后续角色/项目级 policy 扩展保留边界。
8. 不在本节点引入复杂 RBAC；先冻结最小 capability contract。

建议新增：

```text
security/tool_permission.py
tests/test_tool_permission.py
```

**下一步：实现最小 `ToolPermissionPolicy` + capability contract + deny-by-default 专项测试；通过专项测试及全量 pytest 后再进入 5.6。**

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

**当前节点：Phase 5.5 Tool Permission Policy。**

1. 用户 Pull 最新提交。
2. 基于现有 Tool Contract / Registry / Argument Validation / WorkspaceSandbox 建立最小 capability policy。
3. 新增 `security/tool_permission.py` 与专项 contract tests。
4. 验证 deny-by-default、read/write/execute capability 以及 permission failure boundary。
5. 运行专项测试。
6. 运行全量 `pytest -q`。
7. 用户验收通过后，将 5.5 标记完成并进入 5.6 Tool Error Contract。
