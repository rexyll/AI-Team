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
✓ 14.4 Multi-process execution
▶ 14.5 Exactly-once / at-least-once semantics
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

## `✓ 14.4` Multi-process execution
已完成 worker lease、durable ownership、OS-level per-task process lock，以及 result commit fencing：
- 一个 task 同时只能存在一个有效 worker lease；
- lease 带独立 `worker_id`、`lease_id` 与 TTL；
- lease 到期后允许其他 worker 接管；
- stale worker 不能 renew/release 已被其他 worker 接管的 lease；
- ownership 可以跨 store 实例从 durable lease store 恢复；
- task result commit 必须先通过当前 lease ownership 验证；
- lease takeover 后旧 worker 的 late result 被拒绝；
- 没有 active lease 的 result commit 被拒绝；
- rejected result 不执行 apply callback；
- filesystem reference backend 的 lease 与 commit boundary 使用 OS-level per-task process lock；
- 独立进程 regression tests 验证同一 task 的 fencing 行为；
- 用户已确认专项、Phase 14 回归及全量 `pytest -q` 全部通过。

## `▶ 14.5` Exactly-once / at-least-once semantics
第一阶段已开始，明确执行与交付语义：
- execution layer 定义为 **at-least-once**，允许 retry / crash recovery 导致重复执行；
- delivery layer 引入稳定 `task_id + attempt + delivery_id` identity，并通过 SHA-256 形成持久化 key；
- 新增 `runtime/delivery_store.py`，提供 filesystem-backed durable delivery record；
- delivery 状态明确区分 `processing` 与 `committed`；
- duplicate committed delivery 不再次执行 callback；
- delivery record 可跨新的 store/process 实例恢复；
- 独立进程只能有一个 worker 成功 reserve 相同 delivery identity；
- `ResultCommitFencer` 已接入 durable delivery dedup，同时继续保留 lease ownership fencing；
- `processing` 在 crash 后故意保留，避免把 crash-after-apply / before-ack 错误地宣称为 exactly-once。

### 14.5 下一阶段
1. 将 delivery identity 与真实 Task result persistence 建立同一 durable boundary；
2. 设计 crash-after-apply / before-ack 的恢复协议；
3. 明确 `processing` delivery 的 recovery / takeover policy；
4. 验证两个独立进程提交同一 delivery 时最多产生一个 durable effect；
5. 将 dedup 状态纳入审计与 observability；
6. 完成跨进程 crash / retry regression；
7. 用户专项与全量测试通过后关闭 14.5。

> 重要语义边界：通用 Python callback 无法单独提供跨进程真正的 exactly-once effect。当前 reference implementation 提供 durable deduplication 与明确的 crash-recovery 状态；真正 exactly-once effect 必须让业务 mutation 与 delivery record 共享事务或使用本身幂等的 durable sink。

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