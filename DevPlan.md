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

Phase 7.1 / 7.1.1 / 7.2 / 7.3 / 7.4 / 7.4.1 / 7.4.2 / 7.4.3 / 7.5.1 / 7.5.2 / 7.5.3 / 7.5.4 / 7.5.5 / 7.5.6 / 7.6.1 / 7.6.2 / 7.6.3 / 7.6.4 / 7.6.5 / 7.6.6 / 7.6.7 / 7.6.8 已完成。

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
### <span style="color:green">√</span> 7.6.7 Workflow event replay / project recovery integration
### <span style="color:green">√</span> 7.6.8 Workflow event runtime persistence integration

已覆盖 immutable event identity、JSON payload、append / append-if-absent / merge conflict 语义、filesystem atomic persistence、corruption / filename identity boundary、Workflow / Orchestrator 生命周期事件、filesystem 与 in-memory event log 的全局/project/task 有序查询一致性、从 filesystem 一次性恢复独立 `WorkflowEventLog`、project recovery 时独立恢复 event stream，以及 runtime event sink 的可选 durable persistence 边界。

### 7.6.7 实现结果
- `ProjectOrchestrator.resume_persisted()` 增加可选 `event_persistence` 注入入口。
- 提供独立 `WorkflowEventLog` recovery，不把 event stream 嵌入 project snapshot。
- recovery 复用 `WorkflowEventPersistenceAdapter.load_log()`，保持既有 identity / conflict semantics。
- legacy recovery 在不提供 event persistence 时保持原行为，`workflow_event_log` 保持 `None`。
- event recovery failure 保持 fail-fast，不静默吞掉 corruption。
- 恢复后的 `WorkflowEventLog` 与 persistence adapter 独立；修改内存日志不会修改磁盘 event stream。
- `project.resumed` 作为 project event history 的恢复边界事件，保持 project 查询结果中的确定性尾事件语义。
- event recovery 不驱动任务重新执行，不修改 TaskManager、ProjectResult 或 tool execution history。

### 7.6.7 用户最终验收

```text
pytest tests/test_project_workflow_event_recovery_contract.py tests/test_workflow_event_persistence_query_contract.py tests/test_workflow_event_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py -q
32 passed in 0.95s

pytest -q
820 passed in 2.59s
```

7.6.7 已正式验收完成。

### 7.6.8 实现结果
- `WorkflowEventLog` 增加可选 persistence sink，默认仍保持纯 in-memory legacy 行为。
- runtime 新事件先通过 durable sink 持久化，再进入内存事件索引；persistence failure fail-fast，不静默吞错。
- sink 复用 `WorkflowEventPersistenceAdapter` 已有 append-if-absent / conflict semantics，不复制 event identity 规则。
- `ProjectOrchestrator` 增加 runtime workflow event persistence 注入边界，runtime event stream 可以直接落盘。
- runtime persistence 不改变 TaskManager / ProjectResult 状态机，不因写盘失败重试 agent/tool。
- project snapshot 与 workflow event stream 保持存储隔离。
- 覆盖 enabled / disabled sink、idempotency / conflict、failure injection、ordering、recovery 与 snapshot isolation。

### 7.6.8 用户最终验收

```text
pytest tests/test_workflow_event_runtime_persistence_contract.py tests/test_workflow_event_persistence_query_contract.py tests/test_workflow_event_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py tests/test_project_workflow_event_recovery_contract.py -q
38 passed in 1.01s

pytest -q
826 passed in 2.80s
```

最终实现 commit：`4dec49cbb91bccf24eafead1d262a009aade2bbc`。

7.6.8 Workflow event runtime persistence integration 正式验收完成。

---

# 7.6.9 Workflow event replay / state projection

## 目标
在 7.6.6 的 event log rehydration、7.6.7 project recovery、7.6.8 runtime persistence 基础上，建立一个**只读、确定性、无副作用的 workflow event replay / state projection 层**：能够从已经持久化或恢复的事件流计算任务 / 项目在某个事件边界上的可观察状态，用于审计、恢复诊断和后续 replay 能力建设。

本节点只做 **event stream → read-only projection**，不让 replay 反向驱动 Agent、TaskWorkflow 或 Orchestrator，也不直接修改 TaskManager / ProjectResult。

## 实施范围
1. 新增最小 replay / projection API，输入 `WorkflowEvent` 序列或 `WorkflowEventLog`，输出不可变或调用方不可修改的 projection snapshot。
2. 定义当前已有生命周期事件的 projection 规则，至少覆盖：`task_started`、`developer_completed`、`developer_failed`、`tester_skipped`、`tester_completed`、`tester_failed`、`review_started`、`reviewer_approved`、`reviewer_revision`、`task_failed`、`task_retrying`、`task_completed`、`project.resumed`。
3. projection 必须按 event log 的确定性排序消费事件；相同 `occurred_at` 时复用现有 event ordering / tie-breaker 语义，不自行定义第二套排序规则。
4. 对未知 event type 采用明确且稳定的兼容策略：默认保留事件但不改变已知 projection state，不得因为未来新增事件类型导致旧 replay 失败。
5. 对 malformed / inconsistent event payload 提供 fail-fast contract；错误必须指出事件 identity，不能静默产生错误状态。
6. replay 必须是纯读取操作：不得写 filesystem、不得追加 event、不得修改原 `WorkflowEventLog`、不得修改 TaskManager / ProjectResult。
7. 为 project / task 两级 projection 提供最小查询能力，至少能够回答：当前生命周期状态、最后一次已知事件、retry 次数、最后已知错误 / review 状态等已有事件可推导信息。
8. 增加 contract / integration tests，覆盖：
   - 空 event stream；
   - 单 task 正常完成 replay；
   - retry / failure / revision 多轮 replay；
   - `project.resumed` recovery marker；
   - deterministic ordering；
   - unknown event compatibility；
   - malformed payload fail-fast；
   - projection 与原 event log / TaskManager 对象隔离；
   - replay 无 persistence side effect；
   - persisted event stream → rehydrated log → projection 的完整链路。
9. 不在本节点实现 event-driven execution、自动恢复执行、消息队列 consumer、远程 event store、事件压缩或归档。
10. 专项测试通过后运行全量 `pytest -q`。
11. 用户验收后更新 DevPlan，记录测试数量、耗时和最终 commit SHA，再规划 7.6.10。

## 完成判定
- 已持久化 workflow event stream 可以被确定性 replay 为只读 projection；
- projection 不产生任何 runtime / persistence side effect；
- 已知 lifecycle events 的状态转换语义稳定；
- unknown event type 向前兼容；
- malformed / inconsistent event fail-fast；
- 7.6.1–7.6.8 无回归；
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

**当前节点：7.6.9 Workflow event replay / state projection。**

### 下一轮详细计划
1. 先检查现有 `WorkflowEvent`、`WorkflowEventLog`、`WorkflowEventPersistenceAdapter` 以及生命周期事件产生路径，整理已有 event type 与 payload schema，不重复定义已经存在的事件语义。
2. 设计独立的 read-only projection 模块，优先保持纯函数 / value-object 风格，不让 projection 层依赖 Agent、TaskManager 或具体 persistence adapter。
3. 定义 task / project projection 的最小状态模型与事件转换表，并明确 retry、failure、revision、resume marker 的边界。
4. 增加 replay contract tests，再补 persisted event stream → rehydrate → projection integration test。
5. 增加 malformed / unknown event failure / compatibility tests，确保未来事件扩展不会破坏历史 replay。
6. 完成代码后通知用户 Pull；用户先运行专项测试，再运行全量 `pytest -q`。
7. 测试失败时只修复 7.6.9 当前问题，不推进下一节点。
8. 用户确认全量通过后，我更新 DevPlan 为 `√ 7.6.9` 并记录最终 commit SHA。

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

## 2026-08-22 — 7.6.7 验收
- `ProjectOrchestrator.resume_persisted()` 增加可选 workflow event persistence recovery 入口。
- 独立 event stream 通过 `WorkflowEventPersistenceAdapter.load_log()` 恢复，不嵌入 project snapshot。
- 覆盖 persisted project + event recovery、legacy compatibility、corrupt event fail-fast、event-log 对象独立、identity/query consistency，以及 recovery 不改变 TaskManager / ProjectResult。
- 补充 `project.resumed` recovery marker 的确定性尾事件语义。
- 用户确认专项测试：`32 passed in 0.95s`。
- 用户确认全量测试：`820 passed in 2.59s`。
- 7.6.7 Workflow event replay / project recovery integration 正式完成。
- 下一节点进入 7.6.8 Workflow event runtime persistence integration。

## 2026-08-22 — 7.6.8 验收
- `WorkflowEventLog` 增加可选 durable persistence sink，legacy in-memory-only caller 保持兼容。
- runtime event persistence 复用既有 append-if-absent / conflict semantics，并保持 failure fail-fast。
- `ProjectOrchestrator` 支持 runtime workflow event persistence；event stream 与 project snapshot 保持独立存储边界。
- 用户确认专项测试：`38 passed in 1.01s`。
- 用户确认全量测试：`826 passed in 2.80s`。
- 最终实现 commit：`4dec49cbb91bccf24eafead1d262a009aade2bbc`。
- 7.6.8 Workflow event runtime persistence integration 正式完成。
- 下一节点进入 7.6.9 Workflow event replay / state projection。
