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
✓ 14.1 Cancellation contract
▶ 14.2 Timeout contract
□ 14.3 Crash recovery matrix
□ 14.4 Multi-process execution
□ 14.5 Exactly-once / at-least-once semantics
□ 15.x Security Hardening
□ 16.x Observability / Operations
□ 17.x Developer Experience
□ 18.x Release / Production Readiness
```

# Phase 14 — Concurrency / Cancellation / Recovery

## `✓ 14.1` Cancellation contract
已完成 cooperative cancellation primitive 与 lifecycle integration：
- `CancellationToken` 线程安全、单调、幂等；
- 首次 cancellation reason 保留；
- `Task.cancel()` 进入终态 `CANCELLED`；
- cancellation 不写 Task.error、不消耗 retry budget；
- cancelled task 不进入 DependencyScheduler ready/runnable；
- cancelled task 不得新 admission；
- running cancelled task 由 coordinator 幂等释放 resource slot；
- cancellation state 可持久化恢复；
- cancellation lifecycle 专项与全量测试已通过。

## `▶ 14.2` Timeout contract
当前已建立 cooperative timeout 第一层 contract：
- `TimeoutController` 使用 monotonic clock；
- `timeout_s=None` 表示不启用 timeout；
- timeout 必须为正数；
- deadline 到达时 timeout 只产生 control-plane cancellation，不直接修改 Task.failure / retry state；
- timeout 使用独立的 `TimeoutExceeded` 异常语义；
- timeout 与 pre-existing operator cancellation 不覆盖原 cancellation reason；
- `remaining()` 永不返回负数；
- expiry / snapshot / cancellation request 均为幂等；
- 新增 `tests/test_timeout.py`；
- 下一步需把 timeout 接入 Task lifecycle、scheduler admission 与 resource release，并建立 timeout × retry/recovery boundary contract。

## `□ 14.3` Crash recovery matrix
## `□ 14.4` Multi-process execution
## `□ 14.5` Exactly-once / at-least-once semantics

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