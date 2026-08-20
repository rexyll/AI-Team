# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Pull → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 4 — LLM Abstraction**

最新用户验收：

```text
pytest tests/test_workflow_llm_independence.py -q
3 passed in 0.60s

pytest -q
451 passed in 0.95s
```

**Phase 4.4 Workflow → LLM-independent 已完成。**

工作树：由用户本地确认；上一节点已同步且 clean。

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

## ☐ 4.5 Provider/config 可替换

目标：验证并固化 provider/config 的可替换性：同一 Workflow / Agent execution path 可以通过 `BaseLLM` 注入不同实现，而无需修改 Workflow 代码。

本节点重点：

1. 明确 LLM provider configuration 与 Agent execution 的边界。
2. 为不同 `BaseLLM` 实现建立统一注入契约。
3. 验证同一 Agent / Workflow 可在 MockLLM 与 ProviderLLM-compatible fake 之间切换。
4. 禁止 Workflow 根据 provider 名称、model 名称或配置类型分支。
5. 确保默认配置仍保持现有运行路径兼容。

**下一步：先新增 4.5 provider/config substitution contract tests；专项测试通过后运行全量 pytest，再正式关闭 4.5。**

# Phase 5 — Tool / Sandbox Architecture

## ☐ 5.1 Tool Contract
## ☐ 5.2 Tool Registry Contract
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
| √ | `—` | 4.4 user validation: 451 passed |
| ☐ | — | 4.5 Provider/config 可替换 |

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

---

# 当前下一动作

**4.5 Provider/config 可替换**

执行路径：

```text
Configuration
      ↓
BaseLLM implementation
   ↙             ↘
MockLLM       ProviderLLM
      \          /
       \        /
          Agent
            ↓
         Workflow
```

下一步：建立 `tests/test_provider_config_substitution.py`，先验证同一 Agent / Workflow execution path 可以替换不同 `BaseLLM` 实现，同时确保 Workflow 完全不感知 provider/config。
