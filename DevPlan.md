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
已完成第一阶段 worker ownership / lease contract，以及第二阶段 durable ownership：
- 一个 task 同时只能存在一个有效 worker lease；
- lease 带独立 `worker_id`、`lease_id` 与 TTL；
- lease 到期后允许其他 worker 接管；
- stale worker 不能 renew/release 已被其他 worker 接管的 lease；
- release 幂等；
- 新增 filesystem-backed `DurableTaskLeaseStore`，使 ownership 不依赖 Python process-local memory；
- durable lease 使用 atomic temporary-file replacement；
- 新 worker 可以通过 durable lease store 观察既有 ownership；
- lease expiration 后可以执行 ownership takeover；
- stale worker 无法修改 recovered ownership；
- 已新增 `runtime/task_lease_store.py` 与 `tests/test_task_lease_store.py`；
- 当前仍是单机 durable reference backend，不宣称已经具备数据库/分布式系统级 fencing 能力。

### 下一小阶段：ownership fencing × task result commit
重点验证：
1. task result commit 必须携带当前 `lease_id`；
2. lease 被 takeover 后旧 worker 的 late result 必须被拒绝；
3. completed task 不能被旧 worker 覆盖；
4. recovery worker 必须先 acquire 新 lease；
5. release / renew / commit 必须保持 ownership 一致性；
6. 为 14.5 exactly-once / at-least-once 语义建立明确的 delivery boundary。

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