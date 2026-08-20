# AI-Team DevPlan

> 分支：`refactor/runtime-architecture`  
> 开发纪律：**GitHub 原始代码 → 小范围修改 → 专项测试 → 全量 pytest → 用户 Push → 记录最终 SHA → DevPlan √ → 下一节点**

## 当前状态

**Phase 4 — LLM Abstraction**

最新用户验收：

```text
pytest -q
437 passed in 27.34s
```

工作树：由用户本地确认。

---

# Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.4.6 Legacy dependency bridge isolation

已将 Legacy dependency compatibility 收敛到独立 `LegacyDependencyBridge`，canonical completed dependency snapshot 优先，legacy fallback 仅作为兼容路径，并保持 `AgentContext.dependency_context` 稳定接口。

验收基线：

```text
424 passed in 11.84s
```

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

相关 commits：

- `e97132d2ffb6d2222c6d4d2dff450d11b7cca` — `feat: add deterministic MockLLM implementation`
- `d72f59b72ce9541deb5b983097ac1277661e9c30` — `test: define MockLLM deterministic contract`

用户全量验收：

```text
pytest -q
437 passed in 27.34s
```

**结论：4.2 MockLLM 已完成。**

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

新增：

```text
runtime/llm/provider.py
tests/test_provider_llm.py
```

ProviderLLM 只负责：

- 接收 `BaseLLM.generate()` 标准参数
- 构造 system/user messages
- 转发 model / temperature / max_tokens
- 返回纯文本结果
- 不暴露 provider client 给 Agent

提交：

- `52ebb7d4d06ff5d401649401290432833e627154` — `feat: add provider BaseLLM adapter`
- `b701fc6fef7d531eb8ca7cffcfcdc5275c7cd24d` — `test: define ProviderLLM adapter contract`

**下一步：用户 Pull 后运行 `pytest tests/test_provider_llm.py -q`，再运行全量 `pytest -q`。**

## ☐ 4.3.2 Agent LLM injection

专项目标：

1. BaseAgent 增加可注入 `BaseLLM` 的 execution dependency。
2. Architect / Tester / Reviewer 由 `ask_ai` 迁移到 `self.llm.generate()`。
3. Developer 保持现有 tool-calling loop，不直接把 tool schema 粗暴塞进 BaseLLM；先定义其 provider/tool-capable adapter 边界。
4. 默认运行路径继续使用 `ProviderLLM`，保持现有环境变量和 provider 配置兼容。
5. `MockLLM` 可以直接替换 Agent 的真实模型进行测试。
6. 保持 `run(Task) -> AgentResult`、AgentContext access policy 和 Workflow 行为不变。

## ☐ 4.4 Workflow → LLM-independent
## ☐ 4.5 Provider/config 可替换

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
| √ | `52ebb7d4` | ProviderLLM adapter |
| √ | `b701fc6` | ProviderLLM contract tests |

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

---

# 当前下一动作

**4.3.2 Agent LLM injection**

执行路径：

```text
BaseAgent
   ↓
BaseLLM dependency injection
   ↓
Architect / Tester / Reviewer
   ↓
MockLLM / ProviderLLM
```

Developer 则单独处理 tool-capable LLM adapter，避免破坏现有 Tool Calling Loop。

完成 4.3.2 后，再进入 **4.4 Workflow → LLM-independent**。
