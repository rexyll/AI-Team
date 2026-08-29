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
第一阶段建立 worker ownership / lease 基础：
- 一个 task 同时只能存在一个有效 worker lease；
- lease 带独立 `worker_id`、`lease_id` 与 TTL；
- lease 到期后允许其他 worker 接管；
- stale worker 不能 renew 已被其他 worker 接管的 lease；
- stale worker 不能 release 新 worker 的 lease；
- release 对同一 lease 幂等；
- lease coordinator 使用 lock 保护本地并发访问；
- 当前实现作为多进程持久化/分布式协调之前的 reference contract，不宣称跨进程共享内存能力；
- 新增 `runtime/multi_process.py` 与 `tests/test_multi_process.py`。

### 下一小阶段：Multi-process × durable ownership
重点验证：
1. worker lease 能与 durable Task snapshot 绑定；
2. worker crash 后 lease expiration 能驱动 recovery；
3. recovery worker 必须先取得新的 ownership；
4. 旧 worker 无法继续提交结果；
5. lease renewal 与 timeout/cancellation 保持边界；
6. 跨进程实现不能依赖 Python process-local memory。

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