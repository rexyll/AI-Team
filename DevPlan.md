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
✓ 12.5 Developer Reliability Acceptance Matrix
✓ 13.1 1k-task dependency graph
✓ 13.2 5k-task scalability
▶ 13.3 Incremental projection
□ 13.4 Persistent indexes
□ 13.5 Resource governance
□ 13.6 Large-project benchmark
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

## `✓ 12.5` Developer Reliability Acceptance Matrix
已完成 Developer 全生命周期 acceptance matrix，覆盖 success、tool/test/review failure、retry、replan、resume、provider failure、reviewer fallback、isolation 和 terminal failure invariants。

完成条件：专项 acceptance matrix + 全量 `pytest -q` 均通过。

# Phase 13 — Large Project Execution

## `✓ 13.1` 1k-task dependency graph
已完成 1,000 task DAG contract：验证 dependency-first topological order、execution layers、parallel branch 聚合、unknown dependency / cycle rejection，以及 graph construction 对源 task definitions 的隔离。用户已确认专项与全量测试通过（1,328 passed）。

## `✓ 13.2` 5k-task scalability
已完成 5,000 task graph / scheduler scalability contract：验证 5k chain、layered dependency graph、ready-set correctness、确定性和 read-only 边界。专项与全量测试已通过。

## `▶ 13.3` Incremental projection
目标：允许大图只投影目标 task 及其传递依赖，避免每次查询扫描整个 dependency graph，并保持 projection 独立、dependency-closed、cycle-safe。

验收重点：
- selected task 的传递依赖完整保留；
- unknown selected task 明确拒绝；
- projection 不修改 source graph；
- empty selection 返回空 graph；
- projection traversal 成本与 reachable subgraph 规模相关，而非完整 graph 规模；
- cycle / malformed dependency 不被静默吞掉。

## `□ 13.4` Persistent indexes
## `□ 13.5` Resource governance
## `□ 13.6` Large-project benchmark

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