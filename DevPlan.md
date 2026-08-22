# AI-Team DevPlan

> 当前唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`
>
> **分支纪律：除非确有必要，禁止创建新分支、禁止随意切换分支。所有后续开发、修复、测试与 DevPlan 更新均在当前唯一开发分支进行。若确需创建/切换分支，必须先明确说明原因、目标分支、切换命令及返回当前开发分支的方法，并等待用户确认。**
>
> **代码修改边界：AI 直接在 GitHub 当前开发分支修改代码；用户负责 Pull 到本地测试。**

## 开发协作固定流程

1. 根据 DevPlan 当前未完成节点制定本轮目标、涉及文件、实现边界和专项测试范围。
2. AI 直接在当前唯一开发分支编写/修改代码；不得为了单个功能点创建临时分支或在历史分支间切换。
3. AI 完成代码后通知用户 Pull；用户先运行专项测试，再运行全量 `pytest -q`。
4. 测试失败时，用户发送实际错误；AI 只依据错误在同一分支修复，不推进下一节点、不顺手引入下一阶段功能。
5. 用户确认全量测试通过后，AI 更新 DevPlan：标记任务完成、记录测试数量/耗时及最终 commit SHA。
6. 完成一个节点后制定下一节点详细计划，等待用户发送“继续按计划推进工作”或同义明确指令后再编码。
7. 若开发中发现 DevPlan 技术细节、顺序、边界或验收标准需要修改，必须先向用户说明原因和方案，未经确认不得修改已确认规划。

## 分支安全原则

- 当前唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`。
- `main`、`refactor/runtime-architecture`、`refactor/runtime-architecture-7.5.3-audit-v2`、`refactor/runtime-architecture-7.5.4-audit-consistency` 及 `origin/tmp/*`、`origin/docs/*` 仅作历史参考。
- 后续默认不 cherry-pick、merge 或切换到这些分支。
- 每次开始新节点，以用户提供的 `git branch -a`、`git status`、`git log` 为事实基线。

---

# 当前状态

**Phase 7 — Persistence / Observability**

Phase 3 Context Lifecycle Governance、Phase 4 LLM Abstraction、Phase 5 Tool / Sandbox Architecture、Phase 6 Workflow / Project Orchestrator 已完成。

Phase 7.1 / 7.1.1 / 7.2 / 7.3 / 7.4 / 7.4.1 / 7.4.2 / 7.4.3 / 7.5.1 / 7.5.2 / 7.5.3 / 7.5.4 / 7.5.5 / 7.5.6 / 7.6.1 / 7.6.2 / 7.6.3 / 7.6.4 / 7.6.5 / 7.6.6 已完成。

## <span style="color:green">√</span> 7.1 Task persistence contract
## <span style="color:green">√</span> 7.1.1 Task persistence adapter
## <span style="color:green">√</span> 7.2 Project persistence
## <span style="color:green">√</span> 7.3 Agent execution records

## <span style="color:green">√</span> 7.4 Project Resume / Recovery
### <span style="color:green">√</span> 7.4.1 Persisted project resume contract
### <span style="color:green">√</span> 7.4.2 ProjectOrchestrator persisted resume integration
### <span style="color:green">√</span> 7.4.3 Recovery consistency / corruption boundaries

已完成 persisted project → runtime state 恢复、Planner-free continuation、TaskManager identity consistency、ProjectResult consistency，以及 corrupt snapshot / identity mismatch / unknown task tool-history 等边界。

## <span style="color:green">√</span> 7.5 Tool execution logs
### <span style="color:green">√</span> 7.5.1 Tool log ownership / persistence contract
### <span style="color:green">√</span> 7.5.2 Project recovery tool-log integration
### <span style="color:green">√</span> 7.5.3 Audit / query observability boundary
### <span style="color:green">√</span> 7.5.4 Cross-boundary Audit Consistency
### <span style="color:green">√</span> 7.5.5 Execution-history dedup / conflict semantics
### <span style="color:green">√</span> 7.5.6 Persistence atomic batch semantics

7.5.5：统一 `execution_id` identity、幂等重复和 conflict 语义，并在 `ToolExecutionHistory`、`ToolExecutionPersistenceAdapter`、project recovery 边界保持一致；batch merge / persistence 在写入前完成冲突检查。

7.5.6：补充 project persistence failure-injection / partial-write contract，验证 `update()` / `checkpoint()` 在原子替换失败、序列化失败等异常路径下不会留下半更新 snapshot，并清理临时文件；保持 7.5.5 execution-history semantics 不回归。

### 7.5.6 用户最终验收

```text
pytest -q
788 passed in 2.26s
```

7.5.6 已正式验收完成。

---

# 7.6 Workflow event log

## 目标
建立独立于最终 project snapshot 的 Workflow 事件日志 contract，使任务状态变化、调度、执行、重试、恢复等运行时事件具备可追踪、可排序、可持久化的 observability 语义，同时保持 Workflow 核心层不依赖具体存储实现。

## 已完成范围
### <span style="color:green">√</span> 7.6.1 WorkflowEvent value object
### <span style="color:green">√</span> 7.6.2 WorkflowEventLog in-memory contract
### <span style="color:green">√</span> 7.6.3 WorkflowEventPersistenceAdapter filesystem contract
### <span style="color:green">√</span> 7.6.4 Workflow / Orchestrator lifecycle integration
### <span style="color:green">√</span> 7.6.5 Filesystem query / ordering parity
### <span style="color:green">√</span> 7.6.6 Workflow event log rehydration / replay boundary

已覆盖 immutable event identity、JSON payload、append / append-if-absent / merge conflict 语义、filesystem atomic persistence、corruption / filename identity boundary、Workflow / Orchestrator 生命周期事件、filesystem 与 in-memory event log 的全局/project/task 有序查询一致性，以及从 filesystem 一次性恢复独立 `WorkflowEventLog` 的 replay boundary。

### 7.6.6 用户最终验收

```text
pytest tests/test_workflow_event_persistence_contract.py -q
10 passed in 0.16s
```

7.6.6 专项测试已通过并正式验收完成。

---

# 7.6.7 Workflow event replay / project recovery integration

## 目标
在 7.6.6 独立 event-log rehydration 基础上，建立 **event log 与 project recovery 的最小集成边界**：恢复一个已持久化项目时，可以同时恢复其独立 workflow event stream，并让上层获得明确的 project-level event history；但 event log 不参与 TaskManager 状态重建，不反向驱动 Workflow 执行，避免把 observability replay 误变成业务状态 replay。

## 实施范围
1. 明确 project persistence 中 workflow event log 的存储边界：event stream 独立于现有 project snapshot，推荐使用 project-scoped event persistence 根目录或等价隔离路径，不把完整 event 列表直接嵌入现有 project snapshot JSON。
2. 为 project recovery 增加可选的 workflow event persistence adapter / event-log 注入入口；保持旧调用方在未提供 event persistence 时完全兼容。
3. 在 `ProjectPersistenceAdapter` / `ProjectOrchestrator` recovery 边界提供明确的事件日志恢复结果，例如 `WorkflowEventLog` 或等价只读/独立对象；不得直接暴露 persistence adapter 的内部状态。
4. recovery 时使用 7.6.6 `load_log()`，不得复制 `_events`、绕过 `WorkflowEventLog.merge()` 或重新实现 conflict semantics。
5. project recovery 必须保持现有 TaskManager / ProjectResult 恢复语义：event log 恢复失败时，默认应 fail-fast，而不是静默丢弃 observability 数据；具体异常类型和边界测试需在实现中明确。
6. event log 恢复不得修改任务状态、retry counter、task result、tool execution history 或 ProjectResult；它只是独立 observability state。
7. 增加 integration contract tests，至少覆盖：
   - persisted project + persisted events 可以一起恢复；
   - 无 event persistence 的 legacy project recovery 保持兼容；
   - 空 event stream 恢复为空 `WorkflowEventLog`；
   - corrupt event 在 project recovery 中 fail-fast；
   - recovery 后修改 `WorkflowEventLog` 不影响磁盘和 project snapshot；
   - event history 与 task/project identity 的查询结果一致；
   - event recovery 不改变 TaskManager / ProjectResult。
8. 不在本节点实现 event replay 驱动任务状态的功能，不允许根据事件重新执行 agent/tool，也不改变 Workflow / Orchestrator 生命周期事件语义。
9. 专项测试通过后运行全量 `pytest -q`。
10. 用户验收后更新 DevPlan，记录测试数量、耗时和最终 commit SHA，再进入 7.6.8。

## 完成判定
- persisted project 可以在可选 event persistence 下恢复独立 workflow event history；
- legacy project recovery 在未配置 event persistence 时保持兼容；
- event recovery 复用 `WorkflowEventPersistenceAdapter.load_log()`；
- event corruption / conflict 不被吞掉；
- event history 不修改 TaskManager、ProjectResult、tool history 等业务恢复状态；
- 不改变 Workflow / Orchestrator 执行语义；
- 7.5.x 与 7.6.1–7.6.6 无回归；
- 全量 `pytest -q` 通过；
- 用户确认测试结果后才能标记 `√`。

---

# Phase 8 — Production Hardening

## ☐ 8.1 Contract Tests
## ☐ 8.2 Failure Injection Tests
## ☐ 8.3 Security Tests
## ☐ 8.4 LLM Mock Integration Tests
## ☐ 8.5 Long-running Workflow Tests
## ☐ 8.6 Performance / Concurrency Tests
## ☐ 8.7 Documentation / Examples

---

# 当前下一动作

**当前节点：7.6.7 Workflow event replay / project recovery integration。**

### 本轮详细计划
1. 先检查 `ProjectPersistenceAdapter`、`ProjectOrchestrator` 当前 recovery API，以及现有 workflow event persistence 的目录/注入边界。
2. 设计最小兼容扩展：event persistence 可选，不改变旧版 `save/load/continue_persisted` 调用方。
3. 在 project recovery 中接入独立 `WorkflowEventLog` 恢复结果；不得把事件写进现有 project snapshot JSON。
4. 新增 integration contract tests，覆盖 project + event recovery、legacy compatibility、empty/corrupt、object independence、identity consistency 和业务状态不变。
5. 仅修改本节点所需 runtime / test 文件，不提前实现 event-driven replay。
6. 完成后通知用户 Pull，并执行专项测试：
   `pytest tests/test_project_lifecycle_contract.py tests/test_project_persistence_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_persistence_rehydration_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py tests/test_workflow_event_project_recovery_contract.py -q`
7. 专项通过后用户执行全量 `pytest -q`。
8. 用户确认全量通过后，我更新本节为 `√ 7.6.7` 并记录最终 SHA。

---

# DevPlan 变更记录

## 2026-08-22 — 固化开发协作与分支纪律
- 固定唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`。
- 明确原则上不创建/切换分支。
- 固定“规划 → GitHub 编码 → 用户 Pull → 专项测试 → 全量测试 → 用户验收 → DevPlan 更新 → 下一节点”的闭环。
- 测试失败时只针对实际错误在当前分支修复，不推进下一功能点。

## 2026-08-22 — 7.5.5 验收
- 用户确认全量测试：`784 passed in 2.22s`。
- 7.5.5 execution-history dedup / conflict semantics 正式完成。

## 2026-08-22 — 7.5.6 验收
- 新增 persistence failure-injection / partial-write contract tests。
- 覆盖 atomic replacement failure、serialization failure、temporary-file cleanup、旧 snapshot 保持可恢复等边界。
- 用户确认全量测试：`788 passed in 2.26s`。
- 7.5.6 Persistence atomic batch semantics 正式完成。
- 下一节点进入 7.6 Workflow event log。

## 2026-08-22 — 7.6.1–7.6.4 验收
- 用户确认全量测试：`807 passed in 2.35s`。
- WorkflowEvent immutable contract、in-memory log、filesystem persistence 以及 Workflow / Orchestrator lifecycle integration 正式完成。
- 下一节点进入 7.6.5 Filesystem query / ordering parity。

## 2026-08-22 — 7.6.5 验收
- 用户确认全量测试：`813 passed in 2.42s`。
- filesystem event persistence 增加 global / project / task ordered query API。
- query ordering 与 `WorkflowEventLog` 保持 parity，并覆盖 corrupt event fail-fast 与 deterministic tie-breaker。
- 7.6.5 Filesystem query / ordering parity 正式完成。
- 下一节点进入 7.6.6 Workflow event log rehydration / replay boundary。

## 2026-08-22 — 7.6.6 验收
- `WorkflowEventPersistenceAdapter` 增加 `load_log()`，通过完整 filesystem event stream 恢复独立 `WorkflowEventLog`。
- 恢复复用 `WorkflowEventLog.merge()`，保持 identity / conflict semantics；不直接操作 `_events`。
- 覆盖空恢复、完整恢复、排序一致性、corruption fail-fast、对象独立和 conflict 边界。
- 用户确认专项测试：`10 passed in 0.16s`。
- 7.6.6 Workflow event log rehydration / replay boundary 正式完成。
- 下一节点进入 7.6.7 Workflow event replay / project recovery integration。
