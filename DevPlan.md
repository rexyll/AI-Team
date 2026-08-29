# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前开发分支：`feature/reviewer-reliability-fallback`
> 更新时间：2026-08-29
>
> **项目目的：构建一个可持续运行、可恢复、可审计、可验证的 AI 软件开发团队。**

---

# 当前执行顺序

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
✓ 12.4 Reviewer Reliability Boundary
✓ 12.5 Developer Reliability Acceptance Matrix
✓ 13.1 1k-task dependency graph
✓ 13.2 5k-task scalability
✓ 13.3 Incremental projection
✓ 13.4 Persistent indexes
✓ 13.5 Resource governance
✓ 13.6 Large-project benchmark
▶ 14.1 Cancellation contract
□ 14.2 Timeout contract
□ 14.3 Crash recovery matrix
□ 14.4 Multi-process execution
□ 14.5 Exactly-once / at-least-once semantics
□ 15.x Security Hardening
□ 16.x Observability / Operations
□ 17.x Developer Experience
□ 18.x Release / Production Readiness
```

# Phase 13 — Large Project Execution

## `✓ 13.1` 1k-task dependency graph
已完成 1,000 task DAG contract：验证 dependency-first topological order、execution layers、parallel branch 聚合、unknown dependency / cycle rejection，以及 graph construction 对源 task definitions 的隔离。用户已确认专项与全量测试通过（1,328 passed）。

## `✓ 13.2` 5k-task scalability
已完成 5,000 task graph / scheduler scalability contract：验证 5k chain、layered dependency graph、ready-set correctness、确定性和 read-only 边界。专项与全量测试已通过。

## `✓ 13.3` Incremental projection
已完成 dependency-closed projection：选定 task 会保留全部传递依赖，projection 与 source graph 隔离，并对 projection 执行 unknown dependency / cycle safety 校验；同时完成 5k 大图下小 reachable subgraph 与完整链 projection contract。

## `✓ 13.4` Persistent indexes
已完成 forward / reverse dependency index、transitive affected-set、immutable snapshot、incremental mutation、full rebuild equivalence、repeated mutation equivalence 与 5k scalability contract。

## `✓ 13.5` Resource governance
已完成 project-level resource governance 与 execution lifecycle integration：
- `ResourceLimits`：并发 task、tool calls、input tokens、output tokens hard limits；
- `ResourceUsage`：单调累计 usage snapshot；
- `ResourceGovernor`：immutable admission/accounting API；
- `ResourceAdmissionDecision`：资源拒绝与 Task failure 明确隔离；
- `ResourceLifecycle`：admit → consume → finish 生命周期；
- `ResourceExecutionCoordinator`：并发 admission、out-of-order finish 与 slot release 的线程安全协调；
- resource rejection 不修改 Task lifecycle、不消耗 retry、不触发 recovery；
- budget exhaustion 不隐式 finish、不回滚既有 accounting；
- success / failure / exception execution path 均具备资源释放 contract；
- 已通过 Resource Governance 专项、execution lifecycle 专项及全量测试。

## `✓ 13.6` Large-project benchmark
已完成可重复的 1k / 5k / 10k-task baseline，并验证 deterministic layered workload、dependency correctness、graph construction、topological sort、execution layers、projection、persistent index、scheduler ready-set、resource admission 与 memory footprint。

基线结果（Windows / 当前开发环境）：
- 1k：graph 0.655ms，topo 0.679ms，layers 1.401ms，projection 0.046ms，index 0.732ms，ready 1.679ms，peak 1.21MB；
- 5k：graph 3.781ms，topo 3.846ms，layers 7.154ms，projection 0.086ms，index 3.752ms，ready 7.229ms，peak 5.78MB；
- 10k：graph 6.874ms，topo 6.410ms，layers 16.052ms，projection 0.112ms，index 10.073ms，ready 15.288ms，peak 11.55MB。

结论：当前 dependency graph / projection / index 的规模增长保持可接受，下一阶段应转向执行控制面的 cancellation / timeout / crash recovery，而非继续优化静态 DAG 基础算法。

# Phase 14 — Concurrency / Cancellation / Recovery

## `▶ 14.1` Cancellation contract
当前已完成 cooperative cancellation primitive，并进入 lifecycle integration checkpoint：
- `CancellationToken` 为线程安全、单调、可重复 request 的取消信号；
- cancellation reason 只接受非空字符串或 `None`；
- 首次 cancellation reason 保留，后续 request 不覆盖；
- `snapshot()` 提供只读状态；
- `raise_if_requested()` 将取消请求转换为 `CancellationRequested`；
- `wait()` 支持等待取消事件；
- `Task` 增加 cancellation state，并通过 `cancel()` 进入终态 `CANCELLED`；
- cancellation 不写入 Task.error，不消耗 retry budget；
- cancelled task 不再进入 DependencyScheduler ready/runnable 集合；
- cancelled task 不得通过 ResourceExecutionCoordinator 新 admission；
- 已运行任务取消后由 coordinator 通过幂等 `cancel(task_id)` 释放 active resource slot；
- cancellation state 可通过 `Task.to_dict()` / `Task.from_dict()` 持久化恢复；
- 新增 cancellation lifecycle integration contract，待用户专项与全量测试确认后关闭 14.1。

## `□ 14.2` Timeout contract
`□ 14.3` Crash recovery matrix
`□ 14.4` Multi-process execution
`□ 14.5` Exactly-once / at-least-once semantics

# Phase 15 — Security Hardening

`□ 15.1` Package / dependency policy
`□ 15.2` Network egress policy
`□ 15.3` Secret isolation
`□ 15.4` Prompt injection resistance
`□ 15.5` Security regression suite

# Phase 16 — Observability / Operations

`□ 16.1` Structured logging
`□ 16.2` Metrics
`□ 16.3` Tracing
`□ 16.4` Operational dashboard
`□ 16.5` Alerting

# Phase 17 — Developer Experience

`□ 17.1` CLI
`□ 17.2` Configuration
`□ 17.3` Plugin API
`□ 17.4` Documentation
`□ 17.5` Example projects

# Phase 18 — Release / Production Readiness

`□ 18.1` Versioning
`□ 18.2` CI matrix
`□ 18.3` Reproducible benchmark
`□ 18.4` Upgrade / rollback
`□ 18.5` Production readiness checklist

---

# 协作纪律

1. 所有开发、修复、测试和 DevPlan 更新均在 `feature/reviewer-reliability-fallback` 进行。
2. AI 修改 GitHub 后，用户 Pull 到本地运行专项测试和全量 `pytest -q`。
3. 测试失败时只修复当前节点，不跨节点推进。
4. 用户确认专项测试和全量测试通过后，才关闭当前节点并进入下一节点。
5. 不通过降低阈值、删除测试或改变测试语义来“修复”问题。