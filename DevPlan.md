# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 5 — Tool / Sandbox Architecture**

最新用户验收：

```text
pytest -q
463 passed in 0.96s
```

**Phase 4.5 Provider/config 可替换已完成。Phase 5.1 Tool Contract 已完成。Phase 5.2 Tool Registry 已完成实现，等待用户专项/全量测试验收。**

工作树：本轮 5.2 修改已直接提交 GitHub；用户 Pull 后运行专项测试和全量 pytest，确认通过后再把 5.2 标记为最终完成。

---

# Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.4.6 Legacy dependency bridge isolation

已将 Legacy dependency compatibility 收敛到独立 `LegacyDependencyBridge`，canonical completed dependency snapshot 优先，legacy fallback 仅作为兼容路径，并保持 `AgentContext.dependency_context` 稳定接口。

**Phase 3 Context Lifecycle Governance 已完成。**

---

# Phase 4 — LLM Abstraction

## <span style="color:green">√</span> 4.1 BaseLLM Contract

已冻结 provider-independent `BaseLLM.generate()` 契约：

```text
BaseLLM.generate(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str
```

## <span style="color:green">√</span> 4.2 MockLLM

完成 deterministic、零网络依赖的 MockLLM：

- 默认 response
- FIFO response queue
- fallback response
- invocation recording
- reset / remaining response
- BaseLLM compatibility
- 参数边界校验

## <span style="color:green">√</span> 4.3.1 ProviderLLM adapter contract

建立 provider-independent `BaseLLM` 与现有 OpenAI-compatible provider client 之间的最小适配层：

```text
Agent
  ↓
BaseLLM.generate()
  ↓
ProviderLLM
  ↓
OpenAI-compatible client
  ↓
provider API
```

ProviderLLM 只负责：

- 接收 `BaseLLM.generate()` 标准参数
- 构造 system/user messages
- 转发 model / temperature / max_tokens
- 返回纯文本结果
- 不暴露 provider client 给 Agent

## <span style="color:green">√</span> 4.3.2 Agent LLM injection

已完成 Agent 侧 LLM dependency injection：

1. `BaseAgent` 支持注入 `BaseLLM`。
2. Architect / Tester / Reviewer 使用 `self.llm.generate()`，不再直接依赖 `ask_ai`。
3. 默认运行路径继续使用 `ProviderLLM`，保持现有 provider 配置兼容。
4. `MockLLM` 可直接替换真实模型进行 deterministic 测试。
5. 保持 `run(Task) -> AgentResult`、AgentContext access policy 和 Workflow 行为不变。
6. Developer 的 tool-calling loop 暂不强行迁移到普通文本 `BaseLLM`，保留独立 tool-capable adapter 边界。

**结论：4.3.2 Agent LLM injection 已完成。**

## <span style="color:green">√</span> 4.4 Workflow → LLM-independent

已完成 Workflow LLM-independence：Workflow / Orchestrator 只依赖 Agent execution contract，不感知具体 LLM provider、`ask_ai` 或 `ProviderLLM`。

新增 contract tests：

```text
tests/test_workflow_llm_independence.py
```

已验证：

- `runtime/workflow.py` 不直接 import provider LLM 或 `ask_ai`
- Workflow 可以执行没有 `.llm` 属性的最小 Agent 实现
- Workflow 依赖 Agent 的 `run(task)` / result contract，而不是具体模型实现
- 保留 Tester quality gate 与 legacy no-Tester workflow 行为

用户最终验收：

```text
pytest tests/test_workflow_llm_independence.py -q
3 passed in 0.60s

pytest -q
451 passed in 0.95s
```

**结论：4.4 Workflow → LLM-independent 已完成。**

## <span style="color:green">√</span> 4.5 Provider/config 可替换

已完成 provider/config substitution contract，并通过用户全量验收：

```text
pytest -q
456 passed in 0.95s
```

新增：

```text
tests/test_provider_config_substitution.py
```

已固化以下架构约束：

1. 同一个 Agent execution contract 可以注入不同 `BaseLLM` 实现。
2. `MockLLM` 与 `ProviderLLM` 可以走同一 Agent / Workflow execution path。
3. Provider model/client configuration 保持在 `ProviderLLM` adapter 内部，不泄漏到 Agent execution contract。
4. Workflow 不允许根据 provider、model 或 provider configuration 分支。
5. Agent LLM injection 必须接受 `BaseLLM`，拒绝任意非 `BaseLLM` 对象。
6. 默认 provider 运行路径继续保持兼容。

**结论：4.5 Provider/config 可替换已完成。**

# Phase 5 — Tool / Sandbox Architecture

## <span style="color:green">√</span> 5.1 Tool Contract

已完成现有 Tool 能力的最小 provider-independent contract 冻结，并新增 `tests/test_tool_contract.py`。

当前契约覆盖：

1. Registry tool name 与 implementation 一一对应。
2. 每个 registered tool 都是稳定 callable，并具有可检查的 execution signature / return annotation。
3. Tool Schema 与 Registry 使用完全一致的 tool names。
4. Schema 保持标准 function-call 结构：`type=function`、`name`、`description`、`parameters`。
5. `required` 参数必须属于 `properties`，避免 schema 自相矛盾。
6. Tool contract 不允许嵌入 OpenAI / Agnes / API key / model / provider 等 LLM-specific configuration。
7. Registry 中必须是独立 function/builtin，不绑定 Workflow 对象。
8. 现有工具的基础类型边界继续由 implementation 自身承担，5.1 不提前引入复杂 validation framework。

用户最终验收：

```text
pytest -q
463 passed in 0.96s
```

**结论：5.1 Tool Contract 已完成。**

## ☐ 5.2 Tool Registry Contract — 实现完成，验收待确认

本轮已完成 Registry abstraction 的第一版最小实现，并新增 `tests/test_tool_registry.py`。

已冻结：

1. `ToolRegistry.register(name, implementation, schema)` 注册接口。
2. `ToolRegistry.get(name)` 查询接口。
3. `ToolRegistry.list()` 枚举接口。
4. `ToolRegistry.schema(name)` 单 Tool schema 查询接口。
5. `ToolRegistry.schemas()` 从 Registry 输出完整 function-call schemas。
6. duplicate name 明确抛出 `ValueError`。
7. unknown tool 明确抛出 `KeyError`。
8. 非法 name / implementation / schema 明确拒绝。
9. schema function name 必须与 registration name 一致。
10. Registry 返回独立 schema snapshot，调用方修改结果不会污染内部 registry。
11. 默认 Tool 集合由 Registry 初始化，现有 `TOOLS[name]` API 保持兼容。
12. Developer tool-calling loop 已改为通过 `TOOL_REGISTRY` 获取 Tool implementation 与 schemas，不再直接把 `TOOLS_SCHEMA` 作为执行边界。
13. 本节点不引入 Sandbox、权限系统或复杂参数校验。

新增：

```text
tests/test_tool_registry.py
```

本轮提交：

```text
fa67866  test: define ToolRegistry contract
549c0de  refactor: introduce ToolRegistry abstraction
0420eed  refactor: route Developer tools through ToolRegistry
```

**状态：实现已完成；必须等待用户 Pull 后执行专项测试和全量 pytest，确认通过后才能将 5.2 标记为最终完成。**

## ☐ 5.3 Tool Argument Validation
## ☐ 5.4 Workspace Sandbox
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

# Commit Ledger — Current milestone

| 状态 | Commit | 节点 |
|---|---|---|
| √ | `6273d14` | Phase 3.4.3 / 3.4.4 completion docs |
| √ | `eb53804` | Legacy Task.context usage inventory |
| √ | `1a65e57` | Phase 3.4.5 completion docs |
| √ | `9c8afc5` | Legacy Task.context retirement boundary |
| √ | `52ebb7d` | ProviderLLM adapter |
| √ | `b701fc6` | ProviderLLM contract tests |
| √ | `8ef9e19` | AgentContext read-only execution contract |
| √ | `c9ce052` | AgentContext role visibility contract |
| √ | `aece0d2` | AgentContext access policy projections |
| √ | `0635762` | Phase 3.4.1 completion docs |
| √ | `55d0482` | Phase 3.4.2 completion docs |
| √ | `6273d14` | Phase 3.4.3 / 3.4.4 completion docs |
| √ | `1a65e57` | Phase 3.4.5 completion docs |
| √ | `eb53804` | Legacy Task.context usage inventory |
| √ | `18a9bb4` | Workflow LLM-independence contract tests |
| √ | `a8a05d0` | Provider/config substitution contract tests |
| √ | `—` | 4.5 user validation: 456 passed |
| √ | `—` | 5.1 Tool Contract user validation: 463 passed |
| ⏳ | `fa67866` | 5.2 Tool Registry contract tests |
| ⏳ | `549c0de` | 5.2 ToolRegistry abstraction |
| ⏳ | `0420eed` | 5.2 Developer Registry integration |

---

# 重要经验

1. Workflow 不能绕过 Tester；质量门禁修改必须先跑完整 Developer → Tester → Reviewer 集成测试。
2. AgentResult 必须保持 legacy compatibility API。
3. AgentContext 必须是 deep-copy snapshot，不能让 Agent 执行污染 Task。
4. AgentContext Access Policy 必须通过 role-specific projection 实现。
5. Runtime projection 与 persistence serialization 必须保持职责分离。
6. Legacy `Task.context` 只能保留最小 compatibility boundary。
7. Canonical runtime state 必须优先于 legacy compatibility data。
8. LLM abstraction 必须先建立稳定 BaseLLM contract，再逐步迁移 Agent。
9. MockLLM 是测试默认替身，不应依赖真实 provider 网络。
10. Provider adapter 不应把 provider-specific API 泄漏到 Agent 或 Workflow。
11. Developer 的 tool-calling loop 与普通文本 generation 是不同能力边界，不能为了接口统一而丢失工具调用能力。
12. Workflow 的职责是编排 Agent execution，不应持有或理解具体 LLM provider 生命周期。
13. LLM 可替换性应通过 Agent dependency injection 实现，而不是通过 Workflow provider 分支实现。
14. Provider/config substitution 必须通过 BaseLLM contract 验证，而不是在 Workflow 中增加 provider-specific 分支。
15. Tool architecture 应继续保持 provider-independent；Tool capability 不应反向污染 BaseLLM 文本生成契约。
16. Tool Contract 先冻结 capability boundary，再逐步增加 Registry、参数校验、Sandbox、权限和错误语义；避免一次性重构所有 Tool 基础设施。
17. Tool Registry 必须成为 Developer tool resolution 与 schema generation 的统一边界；旧 `TOOLS` 仅作为兼容 API 保留。
18. Registry contract 先冻结 duplicate / unknown / invalid registration 语义，再进入参数校验和安全边界，避免多个基础设施变化同时发生。

---

# 当前下一动作

**Phase 5.2 Tool Registry Contract — 用户验收阶段**

请用户 Pull 后首先执行：

```powershell
pytest tests/test_tool_registry.py tests/test_tool_contract.py -q
```

然后执行：

```powershell
pytest -q
```

如果专项和全量均通过，再将 5.2 标记为最终完成，并进入 **5.3 Tool Argument Validation**。
