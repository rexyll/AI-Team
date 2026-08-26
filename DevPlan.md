# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前开发分支：`feature/reviewer-reliability-fallback`
> 当前基线：Context Compaction v2 + Tool Loop Telemetry
>
> **项目目的：构建一个可持续运行、可恢复、可审计、可验证的 AI 软件开发团队。** 系统不是简单的多 Agent Demo，而是让 Planner / Architect / Developer / Tester / Reviewer / Orchestrator 形成稳定的软件工程闭环：用户需求 → 计划 → 依赖调度 → Agent 执行 → Tester 质量门禁 → Reviewer 审核/返工 → 项目结果 → 持久化恢复 → 事件审计与查询。
>
> **生产目标：** Agent 可替换、LLM 可替换、工具受权限控制、工作区受 sandbox 限制、运行状态可持久化、事件可恢复/投影/查询、失败边界可验证，并最终具备复杂项目、长运行、并发、性能、安全、可观测性、文档和发布能力。

---

# 一、协作与分支纪律

1. 所有开发、修复、测试和 DevPlan 更新均在当前开发分支进行。
2. 当前开发分支：`feature/reviewer-reliability-fallback`。
3. AI 直接在 GitHub 当前开发分支修改代码；用户 Pull 到本地运行专项测试和全量 `pytest -q`。
4. 测试失败时只修复当前节点，不顺手推进下一节点。
5. 用户确认全量测试通过后，记录验收结果和最终 SHA，再进入下一节点。
6. 每个节点遵循：**规划 → GitHub 编码 → Pull → 专项测试 → 全量测试 → 真实 benchmark（如适用）→ 验收 → DevPlan 更新**。
7. 不通过降低测试阈值、删除测试或改变测试语义来“修复”性能/正确性问题。

状态标记：
- `□` Planned
- `▶` In Progress
- `√` 用户确认专项测试和全量测试通过
- `✓` 已完成并记录验收证据

---

# 二、总体进度

## 已完成基础阶段

- `Phase 0–2`：Agent 基础结构、Task/Workflow 生命周期、Tester/Reviewer Quality Gate、Dependency、Planner/Project Execution、AgentResult 统一契约。 `√`
- `Phase 3`：AgentContext 正式化与迁移。 `√`
- `Phase 4`：LLM 抽象与 Provider/Mock 注入。 `√`
- `Phase 5`：Tool Contract、Registry、参数校验、Workspace Sandbox、权限策略和错误边界。 `√`
- `Phase 6`：TaskWorkflow、Dependency-aware Orchestrator、并行执行、Retry/Resume、ProjectResult。 `√`
- `Phase 7`：Tool execution history、Audit、Project Persistence、Workflow Event Log、Event Persistence、Recovery、Projection、Operational Query。 `√`

## Phase 8 已完成

- `8.1` Cross-boundary Contract Tests `√`
- `8.2` Failure Injection Tests `√`
- `8.3` Security Tests `√`
- `8.4` LLM Mock Integration Tests `√`
- `8.5` Long-running Workflow Tests `√`
- `8.6.1` Performance baseline `√`
- `8.6.2` Event persistence contention `√`
- `8.6.3` Concurrent query / projection `√`
- `8.6.4` Scheduler scalability `√`
- `8.6.5` Failure + concurrency matrix `√`
- `8.6.6` Performance regression guard `√`
- `8.6.7` Test coverage consolidation `√`

当前已经从“基础架构正确性”进入“复杂项目稳定运行能力”阶段。

---

# 三、Phase 8.6 — Performance / Concurrency Contract（已完成）

## √ 8.6.1 Performance baseline

建立 32 / 128 / 512 task、1 / 4 worker、wall time、tasks/sec、events/sec 的可重复 benchmark。

Canonical workflow lifecycle 不人为增加事件。当前基准场景中每个 task 的事件由真实 lifecycle 决定，例如：

```text
task_started
developer_completed
tester_skipped
review_started
reviewer_approved
```

## √ 8.6.2 Event persistence contention

验证多 worker 并发持久化、immutable event identity、duplicate/conflict、atomic publication、temporary file cleanup 和 rollback。

## √ 8.6.3 Concurrent query / projection

验证 workflow 持续追加 event 时 query/projection 使用稳定 snapshot，不产生 RuntimeError、partial iteration、duplicate/lost event 或写副作用。

## √ 8.6.4 Scheduler scalability

验证 512 ready tasks 不重复、不遗漏、每 task 恰好执行一次，`max_workers` 不越界，dependency ordering 保持正确。

## √ 8.6.5 Failure + concurrency matrix

覆盖 persistence failure、retry、query、reviewer revision、checkpoint failure 的组合竞争条件，并修复 checkpoint failure 边界缺陷。

## √ 8.6.6 Performance regression guard

建立性能回归 contract，禁止事件数量人为膨胀，并保证 projection/query 不出现明显超线性退化。

## √ 8.6.7 Test coverage consolidation

8.6 专项矩阵全部通过，用户已确认全量测试通过。

---

# 四、Context Compaction 专项路线

## √ C1 Context budget contract

建立：
- `max_prompt_chars`
- `max_input_tokens_per_call`
- `context_growth_ratio`
- `llm_calls`
- `tool_calls`
- before/after prompt metrics

## √ C2 ContextCompactingLLM

建立 stable prefix + recent message window + hard prompt/token budget 的统一 compaction 边界。

## √ C3 Real Developer integration

真实 Developer 使用 `ContextCompactingLLM`，benchmark 可以记录真实 LLM profile。

## √ C4 Context Compaction v2

优化：
- recent message window：12 → 8
- old tool evidence 独立限制
- 最终 prompt/token budget 仍由统一 compactor 控制
- 增加 long-run compaction contract

### 已验收真实 benchmark

v1 → v2：

```text
总耗时                  376.949s → 219.950s   ↓41.6%
LLM calls               50 → 30               ↓40.0%
input tokens            252185 → 131511       ↓47.9%
tool calls              114 → 64              ↓43.9%
max_prompt_chars        23904 → 19815         ↓17.1%
max_input_tokens/call   8188 → 6891           ↓15.8%
context_growth_ratio    14.629 → 12.112       ↓17.2%
llm_time_ratio          0.967 → 0.958
completed               4 → 4
failed                  0 → 0
blocked                 0 → 0
```

**结论：Context Compaction v2 达标，下一阶段转向 Tool Loop Efficiency。** `✓`

---

# 五、Phase 10 — Tool Loop Efficiency

> 当前主线。目标不是简单“少调用工具”，而是在保持正确性的前提下减少重复调用、无效调用、大型结果传播和不必要的 LLM decision turn。

## √ 10.1 Tool Loop Telemetry

已经加入 Tool Loop 观测：

- `unique_tool_calls`
- `duplicate_tool_calls`
- `retry_tool_calls`
- `tool_result_chars`
- `largest_tool_result_chars`
- `arguments_hash`
- `result_hash`
- `duplicate_of`
- `retry_of`

新增 contract：`tests/test_tool_loop_telemetry_contract.py`。

验收状态：代码已写入 GitHub，等待用户专项 + 全量测试验收。

## □ 10.2 Real benchmark classification

使用真实 `serial` benchmark 建立 Tool Loop 分类报告：

- unique call
- exact duplicate
- semantic duplicate
- retry
- failure recovery
- exploration
- verification
- progress-producing call

验收要求：至少能解释一个真实 task 的全部 Tool Calls，不依赖人工猜测。

## □ 10.3 Duplicate Tool Call suppression

只在确认 duplicate semantics 后实现：
- 相同 tool + canonical arguments 的短期去重
- 可配置 dedup window
- 不误去重有副作用的 tool
- read-only tool 与 mutating tool 分离策略

必须增加 correctness contract 和 false-positive regression test。

## □ 10.4 Tool Result Evidence Reduction

目标：减少大型 tool output 对后续 LLM call 的传播。

方向：
- result size budget
- old evidence truncation
- structured summary
- file/test output prioritization
- duplicate result reuse

要求：不能破坏 Developer 后续决策所需的关键 evidence。

## □ 10.5 Tool Loop Progress Guard

检测连续调用但没有产生有效工作进展的 loop：

- repeated identical calls
- repeated identical failures
- unchanged workspace state
- unchanged test state
- repeated read-only inspection

达到阈值时触发：重新规划、压缩上下文、请求更高层 reasoning 或安全终止。

## □ 10.6 LLM Call Reduction

在 Tool Loop telemetry 足够稳定后优化 Developer decision loop：

- 合并可并行 tool calls
- 一次 decision 生成多个安全的独立操作
- 减少重复 verification turns
- task-local checkpoint 后减少重新解释

验收核心：相同任务 correctness 不下降，同时真实 benchmark 的 LLM calls / tool calls 显著下降。

## □ 10.7 Tool Loop regression benchmark

固定 benchmark corpus：
- serial
- partial
- independent
- long tool loop
- failure recovery

每次优化必须比较：
- completion rate
- LLM calls
- tool calls
- input tokens
- duration
- duplicate ratio
- retry ratio
- tool result chars

---

# 六、Phase 11 — Context Intelligence

## □ 11.1 Semantic Context Tiers

把 context 分为：
- system contract
- project facts
- task facts
- current work evidence
- recent interaction
- historical evidence

## □ 11.2 Task Checkpoint Summary

在长任务中建立可恢复 checkpoint summary，避免重新读取大量历史 Tool Output。

## □ 11.3 Context Budget Allocator

从固定 recent window 升级为按任务阶段动态分配：
- code work
- test/debug
- review/fix
- recovery

## □ 11.4 Context Quality Contract

不仅测试“上下文足够小”，还测试：
- required evidence 保留
- irrelevant evidence 删除
- stable facts 不丢失
- task identity 不漂移

## □ 11.5 Long-run Context Benchmark

建立 50 / 100 / 500 LLM-call synthetic long-run benchmark，验证 context growth 不随运行时间失控。

---

# 七、Phase 12 — Developer Reliability

## □ 12.1 Work-product verification

Developer 输出必须与 workspace 实际状态一致。

验证：
- files changed
- tests executed
- tests passed
- expected artifacts
- git/worktree state

## □ 12.2 Failure classification

统一区分：
- LLM failure
- tool failure
- environment failure
- test failure
- code failure
- persistence failure
- reviewer rejection
- timeout/cancellation

## □ 12.3 Evidence contract

Tester / Reviewer 不再只依赖自然语言结果，而是使用结构化 evidence。

## □ 12.4 Reviewer reliability

继续强化 reviewer fallback：
- malformed result
- provider failure
- timeout
- retry
- conservative fallback
- audit trail

## □ 12.5 Recovery correctness

验证 Developer / Tester / Reviewer 在 crash / resume 后不会重复执行不可幂等操作。

---

# 八、Phase 13 — Large Project Execution

目标：从“几十/几百 task”扩展到复杂项目。

## □ 13.1 1k-task dependency graph

验证 1,000+ task graph 的构建、cycle detection、ready-set scheduling 和 memory usage。

## □ 13.2 5k-task scalability

验证 5,000+ tasks 下：
- scheduler latency
- dependency lookup
- persistence size
- projection latency
- query latency

## □ 13.3 Incremental projection

避免每次 query 重建整个 project projection。

目标：event append → incremental state update → query O(changed events) 或接近该复杂度。

## □ 13.4 Persistent indexes

为 project/task/event/reviewer/tool execution 建立可恢复索引。

## □ 13.5 Resource governance

增加：
- max active tasks
- max event count
- max workspace size
- max tool output
- max LLM budget
- per-task/per-project timeout

## □ 13.6 Large-project benchmark

固定 1k / 5k task benchmark，形成 CPU、memory、disk、event、query、scheduler 的长期 regression baseline。

---

# 九、Phase 14 — Concurrency / Cancellation / Recovery

## □ 14.1 Cancellation contract

支持 project/task/tool/LLM 层级 cancellation，并保证状态、event、persistence 一致。

## □ 14.2 Timeout contract

覆盖：
- tool timeout
- LLM timeout
- task timeout
- project timeout

## □ 14.3 Crash recovery matrix

模拟：
- process crash
- worker crash
- persistence failure
- network interruption
- partial checkpoint
- concurrent recovery

## □ 14.4 Multi-process execution

在现有线程并发基础上验证多进程 worker / durable event sink 的一致性边界。

## □ 14.5 Exactly-once / at-least-once semantics

明确每类 operation 的执行语义，不对不可幂等工具假设 exactly-once。

---

# 十、Phase 15 — Security Hardening

## □ 15.1 Package / dependency policy

限制 Agent 自动安装依赖的来源、版本和 workspace 范围。

## □ 15.2 Network egress policy

Tool / Agent 默认 deny-by-default，按角色和任务授权网络访问。

## □ 15.3 Secret protection

防止：
- prompt 泄露 secrets
- tool output 泄露 secrets
- logs 持久化 secrets
- benchmark artifacts 泄露 secrets

## □ 15.4 Resource abuse limits

限制：
- shell process
- CPU time
- memory
- disk
- network
- subprocess count

## □ 15.5 Security regression suite

所有安全边界纳入持续 regression，不允许后续功能绕过 sandbox / permission policy。

---

# 十一、Phase 16 — Observability / Operations

## □ 16.1 Unified Run Trace

Project → Task → Agent → LLM Call → Tool Call → Test → Review → Event 建立统一 trace identity。

## □ 16.2 Metrics

标准指标：
- task throughput
- task latency
- LLM calls
- input/output tokens
- tool calls
- duplicate/retry ratio
- context growth
- reviewer revision rate
- failure rate
- recovery rate

## □ 16.3 Structured logs

所有核心 runtime path 输出结构化日志，禁止依赖 stdout 文本解析作为唯一 observability 来源。

## □ 16.4 Operational query API

提供项目运行状态、失败 task、当前 worker、LLM/tool 成本、review 状态的统一查询。

## □ 16.5 Metrics export

为未来 Prometheus/OpenTelemetry 等外部监控保留 adapter，不将核心 runtime 与具体监控产品耦合。

---

# 十二、Phase 17 — CI / Release Engineering

## □ 17.1 CI test matrix

至少覆盖：
- unit
- contract
- integration
- security
- performance regression
- long-running

## □ 17.2 Benchmark artifacts

每次 release 保存 benchmark summary、环境、commit SHA 和配置。

## □ 17.3 Release gates

Release 必须满足：
- 全量 pytest 通过
- 无新增 warning
- performance regression 不越界
- security regression 通过
- recovery matrix 通过
- documentation examples 通过

## □ 17.4 Versioning / changelog

维护 semantic version、CHANGELOG、migration notes。

## □ 17.5 Reproducible environment

提供锁定依赖、环境变量模板、sandbox 配置和 deterministic mock mode。

---

# 十三、Phase 18 — Documentation / Examples / Release Readiness

## □ 18.1 Setup Guide

覆盖 Windows 11 开发环境、Python、venv、Git、环境变量、Provider 配置、测试运行。

## □ 18.2 Architecture Guide

解释：
- Agent
- AgentContext
- Task
- Workflow
- Orchestrator
- LLM
- Tool Registry
- Persistence
- Event Log
- Projection
- Query

## □ 18.3 Extension Examples

提供：
- 自定义 Agent
- 自定义 LLM Provider
- 自定义 Tool
- 自定义 Reviewer
- 自定义 persistence adapter

## □ 18.4 Persistence / Recovery Example

提供完整的项目保存、恢复、event replay、query 示例。

## □ 18.5 Audit / Observability Example

展示如何查询：
- task history
- tool execution history
- workflow events
- reviewer history
- failures

## □ 18.6 Complex Project Example

提供一个中等复杂真实项目示例，至少包含：
- Architect
- 多 Developer
- Tester
- Reviewer
- dependency graph
- retry/revision
- persistence/recovery

## □ 18.7 Production Configuration Checklist

列出 production 必须配置的：
- LLM provider
- token budget
- tool permissions
- sandbox
- persistence
- concurrency
- timeout
- observability
- security

## □ 18.8 Release Readiness

完成 README、CHANGELOG、examples、migration notes、benchmark report 和 release checklist。

---

# 十四、Phase 19 — Complex Project Validation

> 最终目标：证明 AI-Team 不只是测试通过，而是真的可以稳定开发复杂软件。

## □ 19.1 Medium project

目标规模：约 20–50 tasks。

要求：完整 Planner → Architect → Developer → Tester → Reviewer → persistence → query。

## □ 19.2 Large project

目标规模：约 100–300 tasks。

要求：并发 Developer、dependency scheduling、revision、retry、event persistence、recovery。

## □ 19.3 Long-duration project

持续运行数小时级 benchmark，验证：
- memory growth
- event growth
- context growth
- worker stability
- persistence stability
- LLM/tool failure recovery

## □ 19.4 Stress project

组合：
- 复杂 dependency graph
- 大量 tool calls
- tool failures
- test failures
- reviewer revisions
- persistence failures
- cancellation
- recovery

## □ 19.5 Final acceptance report

输出最终生产能力报告：
- correctness
- performance
- concurrency
- context efficiency
- tool efficiency
- reliability
- security
- recovery
- observability
- documentation

---

# 十五、当前验收基线

最近一次真实 `serial` benchmark 已确认：

```text
scenario=serial
developers=1
tasks=4
completed=4
failed=0
blocked=0

duration_s=219.950
llm_calls=30
input_tokens=131511
output_tokens=4709
tool_calls=64
test_commands=10
avg_llm_latency_s=7.022
llm_time_ratio=0.958
utilization=1.000
max_prompt_chars=19815
max_input_tokens_per_call=6891
max_context_growth_ratio=12.112
```

该结果作为 **Context Compaction v2 baseline**，后续 Tool Loop 优化必须与该基线比较，不得只看单项指标。

---

# 十六、当前工作节点

## ▶ 10.1 Tool Loop Telemetry Acceptance

已写入 GitHub，等待本地验证：

```text
pytest tests/test_tool_loop_telemetry_contract.py -q
pytest -q
```

通过后重新运行：

```text
python -m benchmarks.real_developer --live --developers 1 --scenario serial --repeat 1
```

重点观察：

```text
unique_tool_calls
duplicate_tool_calls
retry_tool_calls
tool_result_chars
largest_tool_result_chars
```

## 下一节点

10.2 Real benchmark classification。

**规则：10.1 未完成验收前，不进入 10.2；每完成一个节点立即在本文件将 `□/▶` 更新为 `√` 并记录专项测试、全量测试、benchmark 和 commit SHA。**

---

# 十七、最终路线图

```text
基础架构                 √
Persistence / Events     √
Production Contracts     √
Performance / Concurrency√
Context Compaction v1    √
Context Compaction v2    √
        │
        ▼
Tool Loop Telemetry      ▶  当前
        │
        ▼
Tool Loop Optimization   □
        │
        ▼
Context Intelligence     □
        │
        ▼
Developer Reliability    □
        │
        ▼
Large Project Execution  □
        │
        ▼
Concurrency / Recovery   □
        │
        ▼
Security Hardening       □
        │
        ▼
Observability            □
        │
        ▼
CI / Release Engineering □
        │
        ▼
Documentation            □
        │
        ▼
Complex Project Validation□
        │
        ▼
Production Readiness     □
```

**总原则：先用真实 benchmark 发现瓶颈，再用 contract 固化问题，再修改生产实现，最后用专项 + 全量 + benchmark 验收。**