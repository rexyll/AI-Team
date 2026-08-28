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
✓ 13.3 Incremental projection
▶ 13.4 Persistent indexes
□ 13.5 Resource governance
□ 13.6 Large-project benchmark
□ 14.x Concurrency / Cancellation / Recovery
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

## `▶ 13.4` Persistent indexes
已完成：
- `DependencyIndex.build()` 构建 forward / reverse indexes；
- immutable snapshot 与 source graph isolation；
- `dependencies_of()` / `dependents_of()` 稳定查询；
- `affected_tasks()` 传递 dependent 查询；
- `with_task_dependencies()` 增量更新单 task 依赖，同时维护 reverse index；
- incremental update 与 full rebuild 等价性 contract；
- 5k graph index build/query scalability contract。

最后验收重点：full rebuild equivalence + repeated mutation equivalence + 5k scalability + 全量回归。

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