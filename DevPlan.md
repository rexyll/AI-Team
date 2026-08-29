# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前开发分支：`feature/reviewer-reliability-fallback`
> 更新时间：2026-08-29
>
> **项目目的：构建一个可持续运行、可恢复、可审计、可验证的 AI 软件开发团队。**

---

# 当前执行顺序

```text
✓ 10.x Tool Loop
✓ 11.x Context Engineering
✓ 12.x Reliability / Failure Isolation
✓ 13.x Large Project Scalability
✓ 14.1 Cancellation contract
✓ 14.2 Timeout contract
✓ 14.3 Crash recovery matrix
▶ 14.4 Multi-process execution
□ 14.5 Exactly-once / at-least-once semantics
□ 15.x Security Hardening
□ 16.x Observability / Operations
□ 17.x Developer Experience
□ 18.x Release / Production Readiness
```

# Phase 14 — Concurrency / Cancellation / Recovery

## `✓ 14.1` Cancellation contract
已完成 cooperative cancellation primitive 与 lifecycle integration，并通过专项与全量测试。

## `✓ 14.2` Timeout contract
已完成 timeout lifecycle integration 与 retry/recovery boundary，并通过专项与全量测试。

## `✓ 14.3` Crash recovery matrix
已完成 crash recovery decision matrix、persistence snapshot reconciliation 与 resource reconciliation，并通过专项与全量测试。

## `▶ 14.4` Multi-process execution
已完成 worker lease、durable ownership，以及第三阶段 result commit fencing：
- 一个 task 同时只能存在一个有效 worker lease；
- lease 带独立 `worker_id`、`lease_id` 与 TTL；
- lease 到期后允许其他 worker 接管；
- stale worker 不能 renew/release 已被其他 worker 接管的 lease；
- ownership 可以跨 store 实例从 durable lease store 恢复；
- task result commit 必须先通过当前 lease ownership 验证；
- lease takeover 后旧 worker 的 late result 被拒绝；
- 没有 active lease 的 result commit 被拒绝；
- rejected result 不执行 apply callback，因此不会覆盖新 worker 的结果；
- 新增 `runtime/result_fencing.py` 与 `tests/test_result_fencing.py`；
- 新增 OS-level per-task process lock，使 filesystem reference backend 的 lease acquire/renew/release/owner/commit boundary 可跨独立进程串行化；
- 新增 `runtime/process_lock.py` 与跨进程锁 contract 测试；
- 当前仍是单机 durable reference backend；真正的跨主机分布式 fencing 仍需数据库/外部协调器实现。

### 下一小阶段：cross-process atomic fencing / integration
重点验证：
1. lease validation 与 result persistence 必须具备原子边界；
2. 两个独立 worker 同时提交时最多一个结果生效；
3. lease takeover 与 late commit 竞态不能产生旧结果覆盖；
4. Task terminal state 与 ownership fencing 必须一致；
5. crash recovery、timeout、cancellation 与 ownership 必须统一；
6. 完成后关闭 14.4，再进入 14.5 delivery semantics。

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