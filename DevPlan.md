# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`
>
> **项目目的：构建一个可持续运行、可恢复、可审计、可验证的 AI 软件开发团队。** 系统不是简单的多 Agent Demo，而是让 Planner / Architect / Developer / Tester / Reviewer / Orchestrator 形成稳定的软件工程闭环：用户需求 → 计划 → 依赖调度 → Agent 执行 → Tester 质量门禁 → Reviewer 审核/返工 → 项目结果 → 持久化恢复 → 事件审计与查询。
>
> **生产目标：** Agent 可替换、LLM 可替换、工具受权限控制、工作区受 sandbox 限制、运行状态可持久化、事件可恢复/投影/查询、失败边界可验证，并最终具备并发、长运行、性能、安全和文档示例等生产化基础。

## 协作与分支纪律

1. 所有开发、修复、测试和 DevPlan 更新均在当前唯一开发分支进行。
2. 不创建临时分支，不随意切换历史分支，不 merge/cherry-pick 其他分支；如确有必要必须先说明并获得确认。
3. AI 直接在 GitHub 当前开发分支修改代码；用户 Pull 到本地运行专项测试和全量 `pytest -q`。
4. 测试失败时只修复当前节点，不顺手推进下一节点。
5. 用户确认全量测试通过后，记录验收结果和最终 SHA，再进入下一节点。
6. 每个节点均遵循：规划 → GitHub 编码 → Pull → 专项测试 → 全量测试 → 验收 → DevPlan 更新。

---

# 一、总体进度判断

## 已完成

- Phase 0–2：Agent 基础结构、Task/Workflow 生命周期、Tester/Reviewer Quality Gate、Dependency、Planner/Project Execution、AgentResult 统一契约。
- Phase 3：AgentContext 正式化与迁移。
- Phase 4：LLM 抽象与 Provider/Mock 注入。
- Phase 5：Tool Contract、Registry、参数校验、Workspace Sandbox、权限策略和错误边界。
- Phase 6：TaskWorkflow、Dependency-aware Orchestrator、并行执行、Retry/Resume、ProjectResult。
- Phase 7：Tool execution history、Audit、Project Persistence、Workflow Event Log、Event Persistence、Recovery、Projection、Operational Query 全部完成。
- Phase 8.1：跨 Project → Workflow → EventLog → Persistence → Projection → Query 的端到端契约。
- Phase 8.2：Failure Injection。
- Phase 8.3：Security contract。
- Phase 8.4：LLM Mock integration。
- Phase 8.5：Long-running workflow / bounded parallel execution。

## 当前判断

**架构基础已经达到“可工程化验证”的预期，但尚未达到最终生产化目标。**

目前最大的剩余风险不是基本功能正确性，而是：

1. 高并发下事件持久化与内存事件顺序的性能/一致性边界。
2. 长时间运行任务的资源、线程、事件数量增长和吞吐稳定性。
3. 大规模任务数量下 Query / Projection / Persistence 的复杂度。
4. 并发失败、超时、取消与恢复组合尚未形成系统化 contract matrix。
5. 当前测试大量验证 correctness，但缺少明确的性能预算和回归基线。
6. 文档和 examples 尚不足以证明系统可以被其他开发者独立部署、扩展和使用。

因此调整 Phase 8：**8.6 不只是“跑性能测试”，而是建立 Production Performance & Concurrency Contract；8.7 再完成 Documentation / Examples / Release Readiness。**

---

# 二、Phase 7 — Persistence / Observability

### √ 7.5.1–7.5.6 Tool execution history
- ownership / persistence
- project recovery
- audit/query
- cross-boundary consistency
- dedup/conflict semantics
- atomic batch persistence

### √ 7.6.1–7.6.11 Workflow Event Log
- immutable WorkflowEvent
- in-memory EventLog
- filesystem persistence
- lifecycle integration
- deterministic ordering/query
- rehydration/replay
- project recovery
- runtime durable sink
- read-only state projection
- operational query boundary
- compatibility matrix

代表验收：
```text
7.6.11 专项：56 passed in 1.13s
7.6.11 全量：850 passed in 2.74s
```

---

# 三、Phase 8 — Production Hardening

## √ 8.1 Cross-boundary Contract Tests

覆盖完整 Project → Workflow → EventLog → Persistence → Projection → Query 链路，并验证 memory/persistence/recovery semantic parity。

## √ 8.2 Failure Injection Tests

Commit evidence：`e6002dd`。

覆盖：
- durable event sink failure
- event batch `os.replace()` failure
- project snapshot update/save failure
- pre-existing snapshot preservation
- temporary file cleanup
- failure 后 recovery boundary

测试文件：`tests/test_failure_injection_contract.py`。

## √ 8.3 Security Tests

Commit evidence：`cbcaf17`。

覆盖：
- Tool schema 参数校验
- deny-by-default permission policy
- WorkspaceSandbox path escape 防护
- terminal shell expansion / command injection 防护
- git transport/configuration escape 防护

测试文件：`tests/test_security_contract.py`。

## √ 8.4 LLM Mock Integration Tests

Commit evidence：`3bc9b0d`、`72c55e4`。

覆盖：
- ProviderLLM OpenAI-compatible mapping
- MockLLM deterministic sequence / call snapshot
- Architect / Tester / Reviewer 无网络执行
- Planner mock repair flow
- invalid generation argument validation
- pytest collection warning 修复

最终 warning 修复 commit：`72c55e4`。

## √ 8.5 Long-running Workflow Tests

覆盖 32 个并行长运行任务、Developer revision、Reviewer approval、事件持久化和 QueryService recovery semantics。

核心契约：
- bounded `max_workers`
- 每个 task 两轮 Developer / Reviewer lifecycle
- event 数量和 lifecycle 类型完整
- persistence 与 in-memory event identity 一致
- project/task query 最终均为 completed/approved
- 并行调度产生的跨 task append 顺序不作为错误条件，identity/order contract 分层验证

测试文件：`tests/test_workflow_event_long_running_contract.py`。

---

# 四、当前节点：8.6 Performance / Concurrency Contract

## 8.6.1 Performance baseline

建立可重复的基准测试，而不是只记录一次运行时间。

指标：
- 任务数量：32 / 128 / 512
- worker：1 / 4 / 8 / 16
- event 数量及平均 event/task
- total wall time
- tasks/sec
- events/sec
- persistence writes/sec
- query/project latency
- memory growth

要求：测试不依赖真实 LLM、网络或外部服务。

## 8.6.2 Event persistence contention

验证多个 worker 同时写入 event persistence：
- 不产生 duplicate event
- 不产生 conflicting event identity
- 不遗失成功提交的 event
- temporary files 最终清理
- `list_ids()` 与 log identity parity 保持成立
- persistence failure 不污染 in-memory log

## 8.6.3 Concurrent query / projection

在 workflow 持续追加 event 时并发执行：
- `list_all()`
- `list_for_project()`
- `list_for_task()`
- `WorkflowEventProjector`
- `WorkflowEventQueryService`

要求 read-only 查询不会产生写副作用或破坏 event identity。

## 8.6.4 Scheduler scalability

验证 DependencyGraph + Orchestrator 在大量 ready tasks 下：
- 不重复调度
- 不遗漏 task
- worker 数量受 `max_workers` 约束
- final lifecycle 全部收敛
- event 数量与 task lifecycle 成正比

## 8.6.5 Failure + concurrency matrix

新增组合测试：
- worker 正在执行时 persistence failure
- worker 执行时 query
- reviewer revision 与其他 task 并发
- partial task failure + retry
- project checkpoint 与 event persistence 同时失败
- resume 后继续并行执行

重点不是引入新的 recovery protocol，而是证明现有边界在竞争条件下仍成立。

## 8.6.6 Performance regression guard

建立最小性能预算，避免后续功能让吞吐/延迟出现无意识回归。

初始目标采用相对基线：
- 相同任务规模下，单 worker correctness baseline 作为基准。
- 4 worker 相比 1 worker 应体现可观并行收益；不要求线性扩展。
- 事件持久化不得随 task 数量出现超线性明显退化。
- query/projection 应保持只读且可重复。

**本节点不为了通过 benchmark 修改业务语义。** 如果 benchmark 暴露结构性问题，再单独提出性能修复子节点。

## 8.6.7 测试文件

计划新增：
- `tests/test_workflow_event_performance_contract.py`
- `tests/test_workflow_event_concurrency_contract.py`
- `tests/test_orchestrator_scalability_contract.py`

必要时复用现有：
- `tests/test_workflow_event_long_running_contract.py`
- `tests/test_workflow_event_persistence_contract.py`
- `tests/test_workflow_event_query_contract.py`

## 8.6 验收

1. 专项测试全部通过。
2. `pytest -q` 全量通过。
3. 无新增 pytest warning。
4. 记录 benchmark baseline、worker 配置、任务规模和最终 commit SHA。
5. 若发现真实性能瓶颈，先记录问题并建立 8.6.x 修复节点，不直接扩大范围。

---

# 五、调整后的 8.7 — Documentation / Examples / Release Readiness

8.7 不再只是补 README，而是完成最小可交付工程闭环：

1. Architecture overview
2. Agent extension guide
3. LLM provider / MockLLM 使用方式
4. Tool permission / WorkspaceSandbox 使用方式
5. Project persistence / resume 使用方式
6. Workflow event persistence / query 使用方式
7. Failure / security boundary 说明
8. Long-running / concurrency 配置说明
9. 一个完整 demo project
10. 本地测试与 CI 命令
11. Production readiness checklist
12. Known limitations

验收目标：新开发者只依赖仓库文档即可理解系统边界，并能运行最小 demo。

---

# 六、最终目标 Definition of Done

项目达到最终目标必须同时满足：

- [ ] Planner → Architect → Developer → Tester → Reviewer → ProjectResult 完整闭环。
- [ ] Dependency-aware scheduling 正确。
- [ ] Agent / LLM / Tool 可替换。
- [ ] Tool 权限和 Workspace Sandbox 有安全边界。
- [ ] Project / Task / Tool execution history 可持久化并恢复。
- [ ] Workflow events 可持久化、重放、投影、查询。
- [ ] Failure injection contract 完整。
- [ ] Security contract 完整。
- [ ] Mock LLM integration 可无网络验证。
- [ ] Long-running workflow 可稳定运行。
- [ ] Performance / concurrency contract 建立并有回归基线。
- [ ] Documentation / Examples 足以独立使用。
- [ ] 全量测试通过且无 warning。

---

# 七、当前工作纪律

**当前只推进 8.6。**

8.6 测试失败时只修复性能/并发相关问题；不提前进入 8.7。

用户确认 8.6 专项和全量测试通过后，再将 8.6 标记为 √，记录最终 SHA，并制定 8.7 的具体编码任务。

---

# DevPlan 更新记录

## 2026-08-22
- 依据 GitHub 当前分支代码、DevPlan 与 commit history 重新校准项目进度。
- 明确项目目标从“功能完整”升级为“可恢复、可审计、可验证、可并发、可维护的生产级 AI 软件开发团队”。
- 确认 8.1–8.5 已完成，8.6 为当前唯一开发节点。
- 将 8.6 从单纯 performance test 扩展为 Performance / Concurrency Contract，并新增 baseline、contention、query concurrency、scheduler scalability、failure+concurrency matrix、regression guard 六类开发环节。
- 将 8.7 明确为 Documentation / Examples / Release Readiness。
- 当前 HEAD 基线：`72c55e4`。
