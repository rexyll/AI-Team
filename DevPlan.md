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

**Phase 4.5 Provider/config 可替换已完成。Phase 5.1 Tool Contract 已完成。**

工作树：用户本地已完成全量测试并确认通过；本节点文档更新已提交 GitHub，等待用户 Pull 后进入 5.2。

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

## ☐ 5.2 Tool Registry Contract

目标：将当前简单 `TOOLS` 映射提升为明确、可验证、provider-independent 的 Tool Registry 抽象。

重点：

1. 冻结注册 / 查询 / 枚举接口。
2. 明确 duplicate name、unknown tool、invalid registration 的行为。
3. Registry 输出 Tool Schema 时必须与 callable 保持一致。
4. Developer tool-calling loop 只通过 Registry 获取 Tool，不直接依赖底层实现集合。
5. 不在本节点引入 Sandbox、权限系统或复杂参数校验。

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

---

# 当前下一动作

**Phase 5.2 Tool Registry Contract**

目标：把当前 `tools/registry.py` 中的简单 `TOOLS` 字典提升为正式 Registry abstraction，同时保持现有 Tool implementations 和 Developer tool-calling behavior 兼容。

执行顺序：

```text
现有 TOOLS mapping
    ↓
Registry contract tests
    ↓
ToolRegistry abstraction
    ↓
Developer / schema integration
```

第一步先增加 Registry contract tests，冻结：

1. `register()` / `get()` / `list()` 的最小语义。
2. 重复注册必须有明确、稳定的错误行为。
3. 查询不存在 Tool 必须有明确、稳定的错误行为。
4. Registry 必须拒绝无效 Tool registration。
5. Schema generation 必须来自 Registry，而不是维护第二份脱节的 Tool name 列表。
6. 旧 `TOOLS` API 在迁移期间保持兼容，避免无必要的全局改动。

专项测试通过后，再实现 Registry；最后运行全量 `pytest -q` 并记录最终结果。
