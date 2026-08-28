# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前开发分支：`feature/reviewer-reliability-fallback`
> 更新时间：2026-08-28
>
> **项目目的：构建一个可持续运行、可恢复、可审计、可验证的 AI 软件开发团队。** Planner / Architect / Developer / Tester / Reviewer / Orchestrator 形成稳定的软件工程闭环，并具备复杂项目、长运行、并发、性能、安全、可观测性、持久化恢复和生产化能力。

---

# 一、协作与分支纪律

1. 所有开发、修复、测试和 DevPlan 更新均在 `feature/reviewer-reliability-fallback` 进行。
2. AI 在 GitHub 当前分支修改；用户 Pull 到本地运行专项测试和全量 `pytest -q`。
3. 测试失败时只修复当前节点，不跨节点推进。
4. 用户确认专项测试和全量测试通过后，才关闭当前节点并进入下一节点。
5. 每个节点遵循：**规划 → GitHub 编码 → Pull → 专项测试 → 全量测试 → benchmark（如适用）→ 验收 → DevPlan 更新**。
6. 不通过降低阈值、删除测试或改变测试语义来“修复”问题。

状态：
- `□` Planned
- `▶` In Progress
- `√` 用户确认专项测试和全量测试通过
- `✓` 已完成并记录验收证据

---

# 二、总体进度

## Phase 0–8.6 — 基础可靠性 / 性能 / 并发

`√` Agent 基础结构、Task/Workflow 生命周期、Tester/Reviewer Quality Gate、Dependency、Planner、Project Execution、AgentResult。

`√` AgentContext、LLM abstraction、Tool Contract / Registry、Sandbox / Permission、TaskWorkflow、Retry / Resume、ProjectResult。

`√` Tool execution history、Audit、Project Persistence、Workflow Event Log、Event Persistence、Recovery、Projection、Operational Query。

`√` Cross-boundary / Failure Injection / Security / LLM Mock / Long-running tests。

`√` Performance / concurrency matrix：baseline、event persistence contention、concurrent query / projection、scheduler scalability、failure + concurrency、performance regression guard、coverage consolidation。

---

# 三、Context Compaction

`✓ C1` Context budget contract。

`✓ C2` ContextCompactingLLM。

`✓ C3` Real Developer integration。

`✓ C4` Context Compaction v2：recent window、old tool evidence、统一 prompt/token budget、long-run contract。

真实 benchmark 已证明 v2 相比 v1：duration、LLM calls、input tokens、tool calls、prompt size 和 context growth 均明显下降，且 completion 保持不变。

---

# 四、Phase 10 — Tool Loop Efficiency

## `✓ 10.1` Tool Loop Telemetry

覆盖 unique / duplicate / retry tool calls、result size、arguments/result hash、duplicate/retry lineage。

## `✓ 10.2` Real benchmark classification

已建立 serial / task-level benchmark，能够解释 exploration / execution / verification 以及 duplicate / retry 成本。

## `✓ 10.3` Duplicate Tool Call suppression

已实现保守 exact duplicate/read-only cache、canonical arguments hash、bounded LRU、mutation invalidation、defensive copy；verification evidence 使用独立 ledger。

## `✓ 10.4` Tool Result Evidence Reduction

已实现 structured rendering、result budget、read_file 头尾保留、run_command 诊断 tail、raw/retained telemetry。

## `✓ 10.5` Tool Loop Progress Guard

覆盖 repeated exact calls、repeated failures、stagnant evidence、progress reset 和安全终止。

## `✓ 10.6` LLM Call Reduction

完成低风险 decision-turn 优化路线：decision classification、terminal verification fast-path、task-local checkpoint/evidence reuse、safe batching contract、decision budget，并通过专项及全量测试。

## `✓ 10.7` Tool Loop regression benchmark

已建立固定 regression corpus 和正式 gate，持续比较 completion、LLM calls、tool calls、input tokens、duration、duplicate ratio、retry ratio、tool-result size。

---

# 五、Phase 11 — Context Intelligence

## `✓ 11.1` Semantic Context Tiers

Context 明确区分 system contract、project facts、task facts、current work evidence、recent interaction、historical evidence。

## `✓ 11.2` Task Checkpoint Summary

长任务通过 checkpoint summary 保存可恢复的 bounded execution evidence，避免 replay 完整 tool history。

## `✓ 11.3` Context Budget Allocator

按任务阶段分配 context budget：code work、test/debug、review/fix、recovery。

## `✓ 11.4` Context Quality Contract

已验证 required evidence 保留、irrelevant evidence 删除、stable facts 不丢失、task identity 不漂移；raw `tool_execution_history` 不进入 Agent context。

## `✓ 11.5` Long-run Context Benchmark

已建立长运行 compaction benchmark，验证 large tool outputs / repeated tool loop 下 prompt、input tokens 和 context growth 保持受控。

---

# 六、Phase 12 — Developer Reliability

## `✓ 12.1` Developer Failure Isolation

验证单 Task Developer failure 不污染其他 Task、scheduler 和 project lifecycle；canonical TaskManager 状态边界保持不变。

## `✓ 12.2` Retry / Checkpoint Consistency

Task serialization / deserialization 保留 `retry_attempt`、`max_retries`、`retry_history`、status 和 error；恢复不会重新获得 retry budget。

## `✓ 12.3` Tool-loop Failure Recovery

已验证 tool failure evidence、read-only cache、workspace mutation invalidation、verification reuse 和 progress guard 的边界；不得复用已经失效的 evidence。

## `▶ 12.4` Reviewer Reliability Boundary

当前节点。重点：
- malformed reviewer result
- provider / LLM failure
- timeout / cancellation
- retry 与 conservative fallback
- Developer → Tester → Reviewer 生命周期边界
- fallback 的 audit / workflow event 证据

验收必须保证 reviewer fallback 不吞掉真实 failure、不绕过 TaskManager 状态机、不产生错误 approval。

## `□ 12.5` Developer Reliability Acceptance Matrix

在 12.4 完成后统一覆盖：success、tool failure、test failure、review rejection、retry、replan、resume、provider failure、concurrency。

---

# 七、Phase 13 — Large Project Execution

## `□ 13.1` 1k-task dependency graph
## `□ 13.2` 5k-task scalability
## `□ 13.3` Incremental projection
## `□ 13.4` Persistent indexes
## `□ 13.5` Resource governance
## `□ 13.6` Large-project benchmark

目标：从几十/几百 task 扩展到 1k / 5k task，同时控制 scheduler latency、dependency lookup、persistence、projection、query 和 memory。

---

# 八、Phase 14 — Concurrency / Cancellation / Recovery

`□ 14.1` Cancellation contract
`□ 14.2` Timeout contract
`□ 14.3` Crash recovery matrix
`□ 14.4` Multi-process execution
`□ 14.5` Exactly-once / at-least-once semantics

---

# 九、Phase 15 — Security Hardening

`□ 15.1` Package / dependency policy
`□ 15.2` Network egress policy
`□ 15.3` Secret isolation
`□ 15.4` Prompt injection resistance
`□ 15.5` Security regression suite

---

# 十、Phase 16 — Observability / Operations

`□ 16.1` Structured logging
`□ 16.2` Metrics
`□ 16.3` Tracing
`□ 16.4` Operational dashboard
`□ 16.5` Alerting

---

# 十一、Phase 17 — Developer Experience

`□ 17.1` CLI
`□ 17.2` Configuration
`□ 17.3` Plugin API
`□ 17.4` Documentation
`□ 17.5` Example projects

---

# 十二、Phase 18 — Release / Production Readiness

`□ 18.1` Versioning
`□ 18.2` CI matrix
`□ 18.3` Reproducible benchmark
`□ 18.4` Upgrade / rollback
`□ 18.5` Production readiness checklist

最终 checklist：correctness、security、reliability、performance、observability、documentation、upgrade、recovery。

---

# 十三、当前执行顺序

```text
✓ 10.1 Tool Loop Telemetry
✓ 10.2 Real benchmark classification
✓ 10.3 Duplicate Tool Call suppression
✓ 10.4 Tool Result Evidence Reduction
✓ 10.5 Tool Loop Progress Guard
✓ 10.6 LLM Call Reduction
✓ 10.7 Tool Loop regression benchmark
✓ 11.1 Semantic Context Tiers
✓ 11.2 Task Checkpoint Summary
✓ 11.3 Context Budget Allocator
✓ 11.4 Context Quality Contract
✓ 11.5 Long-run Context Benchmark
✓ 12.1 Developer Failure Isolation
✓ 12.2 Retry / Checkpoint Consistency
✓ 12.3 Tool-loop Failure Recovery
▶ 12.4 Reviewer Reliability Boundary
□ 12.5 Developer Reliability Acceptance Matrix
□ 13.x Large Project Execution
□ 14.x Concurrency / Cancellation / Recovery
□ 15.x Security Hardening
□ 16.x Observability / Operations
□ 17.x Developer Experience
□ 18.x Release / Production Readiness
```

**当前唯一主线任务：12.4 Reviewer Reliability Boundary。**

每个生产修改完成后必须让用户 Pull，在本地运行专项测试和全量 `pytest -q`；用户确认通过后再关闭节点并更新本计划。