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
3. AI在本地修改代码；
4. 测试失败时只修复当前节点，不顺手推进下一节点。
5. 用户确认全量测试通过后，记录验收结果和最终 SHA，再进入下一节点。
6. 每个节点均遵循：规划 → GitHub 编码 → 专项测试 → 全量测试 → 验收 → 用户push→DevPlan 更新。

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

# 四、Phase 8.6 — Performance / Concurrency Contract

## √ 8.6.1 Performance baseline

已完成第一版可重复 baseline contract：

- 任务数量：32 / 128 / 512
- worker baseline：1
- parallel comparison：4
- total wall time
- tasks/sec
- events/sec
- deterministic mock agents
- 4 workers 相比 1 worker 的软并行收益门槛（>5%）

本节点确认 benchmark 必须服从 canonical workflow lifecycle 语义：当前 baseline router 只注册 Developer + Reviewer，Reviewer 首轮直接 `approved` 时，每个 task 产生 5 个事件：

```text
task_started
developer_completed
tester_skipped
review_started
reviewer_approved
```

因此 benchmark 不通过人为增加事件数量来满足测试，而是根据实际 workflow lifecycle 校正 contract。

验收状态：**已通过，用户确认本地专项及全量测试通过。**

## √ 8.6.2 Event persistence contention

已完成并发持久化 contention contract，并修复生产实现边界。

验证：
- 多 worker 同时写入不产生 duplicate event
- conflicting event identity 不覆盖既有 immutable event
- 成功提交的 event 不遗失
- temporary files 最终清理
- `list_ids()` 与 log identity parity 保持成立
- batch `os.replace()` failure 不产生 partial publication
- failure rollback 不污染 pre-existing events

生产实现增加 adapter 级写入锁，并保持 filesystem atomic publication；批量写入继续使用 `os.replace()` 作为 failure-injection / atomic publication boundary。

修复 commit：`0e34ccf`。

验收状态：**专项及全量测试已通过。**

## √ 8.6.3 Concurrent query / projection

目标：在 workflow 持续追加 event 时并发执行：
- `list_all()`
- `list_for_project()`
- `list_for_task()`
- `WorkflowEventProjector`
- `WorkflowEventQueryService`

要求：
- read-only 查询不会产生写副作用
- 查询不会破坏 event identity
- projection/query 只观察稳定 event snapshot
- concurrent append 不产生 `RuntimeError`、partial dict iteration 或重复/丢失 event
- 使用 durable sink 时 memory/persistence identity 保持一致
- 并发 reader 对同一稳定快照得到语义等价结果

生产实现已增加 `WorkflowEventLog` 实例级 `RLock`，保护 append / merge / list / get / serialization 等边界，使查询与投影在并发追加期间基于稳定 snapshot 工作。

实现 commit：`afeca23`。

专项测试：`tests/test_workflow_event_concurrency_contract.py`。

验收状态：**用户已确认专项测试和全量测试通过。**

## √ 8.6.4 Scheduler scalability

已完成 DependencyGraph + Orchestrator 大规模 ready-set 调度能力 contract，不改变既有生命周期语义。

测试文件：`tests/test_orchestrator_scalability_contract.py`。

覆盖：
- 512 个独立 ready tasks 不重复调度
- 不遗漏任何 task
- 每个 task 恰好执行一次
- `max_workers=4` 时实际 active worker 不超过 4
- 所有 task 最终收敛到 `completed`
- root → 大规模 dependent tasks 的 dependency ordering 正确
- 大规模 ready set 不破坏 DependencyScheduler 的决策边界

验收状态：**用户已确认专项及全量测试通过。**

## √ 8.6.5 Failure + concurrency matrix

已完成 failure、retry、event persistence、query、reviewer revision、checkpoint 边界的竞争条件组合 contract，并修复 checkpoint failure 边界下 task state 被错误标记为 failed 的生产缺陷。

测试文件：`tests/test_workflow_event_failure_concurrency_matrix_contract.py`。

覆盖：
- worker 正在执行时 durable event persistence transient failure，并验证失败事件不会提前进入 memory log，后续 retry 可以继续完成
- worker 并行执行期间持续进行 persistence-backed QueryService 查询，验证 query 无写副作用、无重复/丢失 event
- partial task failure + retry 与其他 task 并发推进
- reviewer revision 与其他 task 并发，同时进行 project query
- checkpoint failure 边界下 event identity 不重复、不污染 durable/memory parity

修复 commit：`38aca25`。

验收状态：**用户已确认专项及全量测试通过。**

## √ 8.6.6 Performance regression guard

已建立最小性能预算，防止后续功能让吞吐/延迟出现无意识回归。

初始目标：
- 相同任务规模下，单 worker correctness baseline 作为基准。
- 4 worker 相比 1 worker 应体现可观并行收益；不要求线性扩展。
- 事件持久化不得随 task 数量出现超线性明显退化。
- query/projection 应保持只读且可重复。
- benchmark 的事件数量必须由实际 workflow lifecycle 语义决定，不得为了满足性能测试人为增加事件。

新增回归测试文件：`tests/test_workflow_event_performance_regression_contract.py`。

测试同时验证 canonical workflow lifecycle 下每个 task 恰好产生 5 个事件，不通过人为增加事件数量满足预算。

最后修复 commit：`345f876`（align 8.6.6 regression guard with current AgentResult contract）。

验收状态：**用户已确认专项及全量测试通过。**

## √ 8.6.7 Test coverage consolidation

8.6 Performance / Concurrency Contract 所需测试矩阵已经落地并完成验收，当前测试集合包括：
- `tests/test_workflow_event_performance_contract.py`
- `tests/test_workflow_event_performance_regression_contract.py`
- `tests/test_workflow_event_persistence_contention_contract.py`
- `tests/test_workflow_event_concurrency_contract.py`
- `tests/test_orchestrator_scalability_contract.py`
- `tests/test_workflow_event_failure_concurrency_matrix_contract.py`
- `tests/test_workflow_event_long_running_contract.py`
- `tests/test_workflow_event_persistence_contract.py`
- `tests/test_workflow_event_query_contract.py`

验收标准：
1. 8.6.x 专项测试全部通过。
2. `pytest -q` 全量通过。
3. 无新增 pytest warning。
4. benchmark baseline、worker 配置、任务规模和最终 commit SHA 已具备可追溯证据。

**Phase 8.6 当前状态：全部验收通过。**

---

# 五、下一阶段：Phase 8.7 Documentation / Examples / Release Readiness

8.6 完整验收后进入 8.7，目标为：
- deployment / setup documentation
- Agent / LLM / Tool extension examples
- persistence / recovery usage example
- event query / audit example
- production configuration checklist
- release readiness checklist
- final end-to-end smoke test

## 8.7 推进原则

1. 先读取并整理现有文档、examples 与当前实际 API，禁止按旧接口编写示例。
2. 示例必须使用当前 canonical AgentResult / Task / WorkflowEvent / persistence / query contract。
3. 文档示例必须可以独立运行或明确说明最小运行前置条件。
4. 每个 8.7.x 节点仍遵循：规划 → GitHub 编码 → Pull → 专项测试/示例验证 → 全量测试 → 验收 → DevPlan 更新。
5. 8.7 阶段不改变已经验收的核心 workflow lifecycle semantics，除非专项验证发现真实缺陷。

### √ 8.7.1 Documentation baseline & setup guide

已建立 `docs/setup.md` 并验收，覆盖：
- 项目安装与虚拟环境 setup（§2–§3，requirements.txt 当前保持为空属预期契约）
- 最小运行流程与 CLI 入口（§4，`python main.py "<requirement>"`）
- 测试运行方式与全量验收门禁（§5，`pytest -q` 为每节点最终门禁）
- Agent / LLM provider 配置入口（§6–§7）
- Tool registry / permission / workspace sandbox 配置入口（§8）
- persistence / recovery 基本使用说明（§9）
- 当前支持的 canonical runtime contract 概览（§10）

README 已链接 setup guide 与 DevPlan。

专项测试：`tests/test_documentation_setup_contract.py`。
最终 commit：`817388e`。

验收状态：**用户已确认专项及全量测试通过。**

### √ 8.7.2 Agent / LLM / Tool / Persistence extension examples

已完成可独立运行的扩展示例包并验收：
- `examples/custom_agent.py`：BaseAgent 子类、稳定 role、Task → AgentResult 契约
- `examples/custom_llm.py`：BaseLLM.generate() provider 边界，生产集成不进入编排层
- `examples/custom_tool.py`：ToolRegistry 注册 + function-call schema，不绕过参数校验/权限/sandbox 边界
- `examples/persistence_query.py`：durable event 存储 + 只读 WorkflowEventQueryService 查询
- `examples/README.md`：扩展边界与安全边界说明（registry 非授权边界等）

示例契约规则：示例是当前 API 的文档而非兼容垫片；canonical contract 变化时示例与契约测试同节点更新。

专项测试：`tests/test_extension_examples_contract.py`。
最终 commit：`b79b4c5`。

验收状态：**用户已确认专项及全量测试通过。**

### 8.7.3 Persistence / Recovery and Event Query / Audit example
