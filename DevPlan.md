# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前开发分支：`feature/reviewer-reliability-fallback`
> 更新时间：2026-08-28
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
▶ 12.5 Developer Reliability Acceptance Matrix
□ 13.x Large Project Execution
□ 14.x Concurrency / Cancellation / Recovery
□ 15.x Security Hardening
□ 16.x Observability / Operations
□ 17.x Developer Experience
□ 18.x Release / Production Readiness
```

# Phase 12 — Developer Reliability

## `✓ 12.1` Developer Failure Isolation
验证单 Task Developer failure 不污染其他 Task、scheduler 和 project lifecycle。

## `✓ 12.2` Retry / Checkpoint Consistency
Task checkpoint 保留 retry attempt、budget、history、status 和 error；resume 不重新获得 retry budget。

## `✓ 12.3` Tool-loop Failure Recovery
验证 tool failure evidence、cache、mutation invalidation、verification reuse 和 progress guard 边界。

## `✓ 12.4` Reviewer Reliability Boundary
已完成 Reviewer primary failure、fallback approval、fallback exhaustion、retry lifecycle、TaskManager 状态边界以及 workflow event/audit 集成验收。

关键保证：fallback 不吞掉真实 failure、不绕过 TaskManager 状态机、不产生错误 approval。

## `▶ 12.5` Developer Reliability Acceptance Matrix

当前节点。统一建立 Developer 全生命周期 acceptance matrix，覆盖：

1. 正常成功
2. tool failure
3. test failure
4. review rejection
5. retry
6. retry exhausted / block
7. specification failure / replan
8. resume / checkpoint
9. provider / LLM failure
10. reviewer fallback
11. concurrency / isolation
12. terminal failure 不得产生 false success

验收原则：

- 每一种 failure class 都必须映射到唯一、可解释的 recovery action。
- Recovery action 不得越过 TaskManager canonical state transition。
- retry budget 必须单调消耗，不得因 resume/replan/fallback 意外恢复。
- failure provenance 必须保留。
- terminal failure 必须保持 failed / blocked 等真实终态，不能伪装成 completed。
- workflow event 与 audit evidence 必须能够解释 recovery 路径。

完成条件：专项 acceptance matrix + 全量 `pytest -q` 均通过。

# Phase 13 — Large Project Execution

`□ 13.1` 1k-task dependency graph
`□ 13.2` 5k-task scalability
`□ 13.3` Incremental projection
`□ 13.4` Persistent indexes
`□ 13.5` Resource governance
`□ 13.6` Large-project benchmark

# Phase 14 — Concurrency / Cancellation / Recovery

`□ 14.1` Cancellation contract
`□ 14.2` Timeout contract
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
