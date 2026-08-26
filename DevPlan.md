# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前开发分支：`feature/reviewer-reliability-fallback`
> 当前基线：Context Compaction v2 + Tool Loop Efficiency 10.1–10.5
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

## √ 10.2 Real benchmark classification

真实 `serial` benchmark 已能够解释 task 级 Tool Calls，并输出：
- unique / exact duplicate
- retry
- exploration / execution / verification
- tool result size
- per-call LLM latency / input / output tokens

### 最新真实 benchmark 证据

```text
scenario=serial developers=1 tasks=4
completed=4 failed=0 blocked=0
duration_s=423.791
llm_calls=57
input_tokens=246884
output_tokens=7829
tool_calls=126
unique_tool_calls=82
duplicate_tool_calls=44
retry_tool_calls=2
tool_result_chars=212647
largest_tool_result_chars=7577
max_prompt_chars=24000
max_input_tokens_per_call=7919
max_context_growth_ratio=16.235
```

Task-3 是当前主要优化对象：

```text
llm_calls=29
input_tokens=141296
tool_calls=63
unique_tool_calls=29
duplicate_tool_calls=34
retry_tool_calls=2
tool_result_chars=118552
```

**结论：10.2 达标；真实 benchmark 已证明 duplicate tool call 是下一阶段主要成本来源。** `✓`

## √ 10.3 Duplicate Tool Call suppression

已实现保守的 exact duplicate/read-only cache：
- canonical arguments hash
- bounded LRU window
- `read_file` / `list_files` 才允许缓存
- mutating / execution tool 会失效缓存
- cache hit 返回 defensive copy
- 不改变原始 tool execution history
- verification command 采用独立 evidence ledger，不把副作用命令纳入普通 cache

专项 contract：`tests/test_tool_loop_cache.py`。

同时加入 false-positive 防护：非只读 verification command 不复用，workspace mutation 后 verification 必须重新执行。

用户已确认专项测试和全量测试通过。 `✓`

## √ 10.4 Tool Result Evidence Reduction

已实现 bounded tool evidence：
- structured result deterministic rendering
- result size budget
- `read_file` 保留头尾
- `run_command` 保留诊断 tail
- 旧 tool output 不直接完整传播到下一 LLM turn
- telemetry 同时记录 raw / retained result size

用户已确认专项测试和全量测试通过。 `✓`

## √ 10.5 Tool Loop Progress Guard

已实现：
- repeated exact calls
- repeated failures
- stagnant result evidence
- explicit progress reset
- 可配置阈值
- 触发后安全终止并保留 telemetry / result data

用户已确认专项测试和全量测试通过。 `✓`

## ▶ 10.6 LLM Call Reduction

下一主攻节点。**重点不是继续增加简单去重规则，而是减少 Developer decision turn。**

第一阶段只做低风险、可验证优化：

1. **Decision-turn classification**：区分“需要 LLM 重新推理”的 tool result 与“已有充分 evidence、只需继续执行”的结果。
2. **Terminal verification fast-path**：成功且 mutation-safe 的验证结果已经确认后，避免再次产生无意义 verification decision turn；必须保留最终 AgentResult 正确性。
3. **Task-local checkpoint reuse**：checkpoint 不仅压缩 context，还要携带最近有效 action/evidence，使下一轮不重新探索。
4. **Safe tool batch contract**：对于同一 decision 中彼此独立且明确 read-only 的操作，验证是否可以合并处理；严禁自动并行可能存在依赖或副作用的操作。
5. **Decision budget**：为单 task 设置软性 decision-turn budget；接近预算时优先 checkpoint / evidence reuse，而不是盲目继续探索。

验收要求：
- correctness 不下降
- 不增加 false-positive tool suppression
- 真实 benchmark `llm_calls` 明显下降
- `input_tokens` 与 `tool_calls` 同时观察
- failure/recovery 场景不能被 fast-path 吞掉

**当前状态：设计与验收边界已明确，下一次代码修改从 `Decision-turn classification + terminal verification fast-path` 开始。**

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

10.6 完成后建立正式 baseline / regression gate。

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

Tool / Agent 默认 deny-by-default，按角色和任务授予最小网络权限。

## □ 15.3 Secret isolation

禁止 tool result、prompt、event log、audit log 泄漏 API key / token / credential。

## □ 15.4 Prompt injection resistance

验证 repository content、tool output、test output 中的恶意指令不能改变系统级权限边界。

## □ 15.5 Security regression suite

建立长期 security contract，所有高风险边界进入 CI gate。

---

# 十一、Phase 16 — Observability / Operations

## □ 16.1 Structured logging

统一 task/project/tool/LLM/event correlation id。

## □ 16.2 Metrics

暴露：
- task throughput
- queue latency
- tool latency
- LLM latency
- token usage
- failure rate
- retry rate
- cache hit rate
- duplicate suppression rate

## □ 16.3 Tracing

建立 project → task → agent → LLM call → tool call → event 的 trace。

## □ 16.4 Operational dashboard

提供运行中项目状态、失败 task、阻塞 task、资源消耗和恢复状态。

## □ 16.5 Alerting

针对：
- failure spike
- retry storm
- tool loop stagnation
- token budget exhaustion
- persistence lag
- event backlog

---

# 十二、Phase 17 — Developer Experience

## □ 17.1 CLI

提供：
- project create
- project run
- project status
- task inspect
- task retry
- project resume
- event query

## □ 17.2 Configuration

统一 YAML/TOML configuration，支持 project / role / environment override。

## □ 17.3 Plugin API

允许第三方 Agent / Tool / LLM provider 插件化接入。

## □ 17.4 Documentation

建立 architecture / API / operations / security / extension 文档。

## □ 17.5 Example projects

提供：
- CRUD application
- data pipeline
- API service
- multi-module application
- long-running refactor

---

# 十三、Phase 18 — Release / Production Readiness

## □ 18.1 Versioning

Semantic versioning + migration policy。

## □ 18.2 CI matrix

覆盖 Python / OS / provider / concurrency / persistence combinations。

## □ 18.3 Reproducible benchmark

固定 benchmark environment、seed、dataset 和输出格式。

## □ 18.4 Upgrade / rollback

支持 schema migration、event compatibility 和安全 rollback。

## □ 18.5 Production readiness checklist

完成：
- correctness
- security
- reliability
- performance
- observability
- documentation
- upgrade
- recovery

---

# 十四、下一步执行顺序

当前严格按照以下顺序推进，不跨节点：

```text
√ 10.1 Tool Loop Telemetry
√ 10.2 Real benchmark classification
√ 10.3 Duplicate Tool Call suppression
√ 10.4 Tool Result Evidence Reduction
√ 10.5 Tool Loop Progress Guard
▶ 10.6 LLM Call Reduction
□ 10.7 Tool Loop regression benchmark
□ 11.x Context Intelligence
□ 12.x Developer Reliability
□ 13.x Large Project Execution
□ 14.x Concurrency / Cancellation / Recovery
□ 15.x Security Hardening
□ 16.x Observability / Operations
□ 17.x Developer Experience
□ 18.x Release / Production Readiness
```

**当前唯一主线任务：10.6 LLM Call Reduction。**

每次完成代码修改后，必须先让用户 Pull，在本地专项测试 + 全量 `pytest -q`；用户确认通过后才进入下一子步骤。