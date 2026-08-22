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

Phase 7.1 / 7.1.1 / 7.2 / 7.3 / 7.4 / 7.4.1 / 7.4.2 / 7.4.3 / 7.5.1 / 7.5.2 / 7.5.3 / 7.5.4 / 7.5.5 / 7.5.6 / 7.6.1 / 7.6.2 / 7.6.3 / 7.6.4 / 7.6.5 已完成。

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

已覆盖 immutable event identity、JSON payload、append / append-if-absent / merge conflict 语义、filesystem atomic persistence、corruption / filename identity boundary、Workflow / Orchestrator 生命周期事件，以及 filesystem 与 in-memory event log 的全局/project/task 有序查询一致性。

用户最终验收：

```text
pytest -q
813 passed in 2.42s
```

7.6.5 正式完成。

## 7.6.6 Workflow event log rehydration / replay boundary

### 目标
在 filesystem query contract 之上建立明确的 event-log 恢复边界，使持久化事件能够一次性重新装载到独立的 `WorkflowEventLog`，为后续 project recovery / observability replay 提供稳定入口，同时不把持久化实现耦合进 Workflow 核心执行路径。

### 实施范围
1. `WorkflowEventPersistenceAdapter` 增加 `load_log()`（或等价明确命名）API，返回独立的 `WorkflowEventLog` 实例。
2. 恢复必须基于持久化文件的完整事件集合，并复用 `WorkflowEventLog.merge()` 的 identity / conflict semantics；不得直接操作其内部 `_events`。
3. 恢复后的 log 与 filesystem adapter 的 `list_all()` 事件集合一致，并保持 `WorkflowEventLog` 自身的查询排序语义。
4. 空目录应恢复为空 `WorkflowEventLog`，而不是返回 `None`。
5. corrupt event、非法 event payload、重复 event_id conflict 必须明确失败；不得静默跳过或部分恢复。
6. `load_log()` 返回的新对象必须与 adapter 后续操作、此前创建的 log 相互独立，修改恢复后的 log 不得影响磁盘或其他内存对象。
7. 增加 contract tests：空恢复、完整恢复、顺序一致性、corruption fail-fast、对象独立性，以及 conflict 边界。
8. 不修改 TaskWorkflow / Orchestrator 的执行语义，不把 event log 写入现有 project snapshot；本节点只建立 recovery / replay adapter boundary。
9. 专项测试通过后运行全量 `pytest -q`。
10. 用户验收后更新 DevPlan，记录测试数量、耗时和最终 commit SHA，再进入 7.6.7。

### 完成判定
- filesystem event stream 可恢复为独立 `WorkflowEventLog`；
- 恢复使用既有 in-memory conflict contract；
- corruption / conflict 不被吞掉；
- 空目录得到空 log；
- 不改变现有 Workflow / Orchestrator 行为；
- 7.5.x 与 7.6.1–7.6.5 无回归；
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

**当前节点：7.6.6 Workflow event log rehydration / replay boundary。**

### 本轮详细计划
1. 修改 `runtime/workflow_event_persistence.py`，引入 `WorkflowEventLog` 并实现 `load_log()`。
2. `load_log()` 通过 `self._load_all_events()` 获取完整事件，再调用 `WorkflowEventLog.merge()` 完成恢复，不直接写内部字典。
3. 新增 `tests/test_workflow_event_persistence_rehydration_contract.py`，覆盖空恢复、完整恢复、顺序、corrupt、对象独立和 conflict。
4. 不修改 Workflow / Orchestrator 核心逻辑，不把 event log 放入 project snapshot。
5. 完成后通知用户 Pull，用户执行专项测试：
   `pytest tests/test_workflow_event_persistence_rehydration_contract.py tests/test_workflow_event_persistence_query_contract.py tests/test_workflow_event_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py -q`
6. 专项通过后用户执行全量 `pytest -q`。
7. 用户确认全量通过后，我更新本节为 `√ 7.6.6` 并记录最终 SHA。

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
