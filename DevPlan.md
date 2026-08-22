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
- 原则上不创建、不切换、不 merge/cherry-pick 其他分支。
- 每次开始新节点，以用户提供的 `git branch -a`、`git status`、`git log` 为事实基线。

---

# 当前状态

**Phase 7 — Persistence / Observability**

Phase 3 Context Lifecycle Governance、Phase 4 LLM Abstraction、Phase 5 Tool / Sandbox Architecture、Phase 6 Workflow / Project Orchestrator 已完成。

7.1、7.1.1、7.2、7.3、7.4、7.4.1、7.4.2、7.4.3、7.5.1–7.5.6、7.6.1–7.6.10 已完成。

## 7.5 Tool execution logs

### <span style="color:green">√</span> 7.5.1 Tool log ownership / persistence contract
### <span style="color:green">√</span> 7.5.2 Project recovery tool-log integration
### <span style="color:green">√</span> 7.5.3 Audit / query observability boundary
### <span style="color:green">√</span> 7.5.4 Cross-boundary Audit Consistency
### <span style="color:green">√</span> 7.5.5 Execution-history dedup / conflict semantics
### <span style="color:green">√</span> 7.5.6 Persistence atomic batch semantics

7.5.5 统一 `execution_id` identity、幂等重复与 conflict 语义；7.5.6 补充 persistence failure-injection / partial-write / atomic batch contract。

### 7.5.6 用户最终验收
```text
pytest -q
788 passed in 2.26s
```

---

# 7.6 Workflow event log

## 已完成范围

### <span style="color:green">√</span> 7.6.1 WorkflowEvent value object
### <span style="color:green">√</span> 7.6.2 WorkflowEventLog in-memory contract
### <span style="color:green">√</span> 7.6.3 WorkflowEventPersistenceAdapter filesystem contract
### <span style="color:green">√</span> 7.6.4 Workflow / Orchestrator lifecycle integration
### <span style="color:green">√</span> 7.6.5 Filesystem query / ordering parity
### <span style="color:green">√</span> 7.6.6 Workflow event log rehydration / replay boundary
### <span style="color:green">√</span> 7.6.7 Workflow event replay / project recovery integration
### <span style="color:green">√</span> 7.6.8 Workflow event runtime persistence integration
### <span style="color:green">√</span> 7.6.9 Workflow event replay / state projection
### <span style="color:green">√</span> 7.6.10 Workflow event projection integration / operational query boundary

### 7.6.6–7.6.8 结果摘要
- filesystem event stream 支持 ordered query 与 `load_log()` rehydration。
- project recovery 可独立恢复 workflow event log，并追加确定性的 `project.resumed` recovery marker。
- runtime event log 支持可选 durable persistence sink，失败 fail-fast，且与 project snapshot 存储隔离。

### 7.6.6–7.6.8 用户验收
```text
7.6.6 专项：10 passed in 0.16s
7.6.7 专项：32 passed in 0.95s
7.6.7 全量：820 passed in 2.59s
7.6.8 专项：38 passed in 1.01s
7.6.8 全量：826 passed in 2.80s
```

### 7.6.9 实现结果
- 新增 `runtime/workflow_event_projection.py`。
- 提供不可变 `WorkflowTaskProjection` / `WorkflowProjectProjection`。
- 提供 `WorkflowEventProjector.project()`、`project_task()`、`replay_workflow_events()`。
- replay 复用现有 `WorkflowEventLog._global_sort_key`，保持确定性排序语义。
- 覆盖 task lifecycle、retry、failure、review revision / approval、`project.resumed`。
- unknown event type 向前兼容；malformed / inconsistent known event fail-fast，并包含 `event_id`。
- projection 纯读取，不写 filesystem、不追加 event、不修改 EventLog、TaskManager、ProjectResult。
- 支持 project/task 两级查询：lifecycle、last event、retry、error、review status。
- 覆盖 persisted → rehydrate → projection 以及对象隔离、无 persistence side effect。

### <span style="color:green">√</span> 7.6.9 用户最终验收
```text
pytest tests/test_workflow_event_projection_contract.py tests/test_workflow_event_persistence_query_contract.py tests/test_workflow_event_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py tests/test_project_workflow_event_recovery_contract.py -q
40 passed in 1.06s

pytest -q
834 passed in 2.91s
```

7.6.9 Workflow event replay / state projection 正式验收完成。

### 7.6.10 实现结果
- 新增 `runtime/workflow_event_query.py`，建立 read-only operational query boundary。
- 提供 `WorkflowEventQueryService.from_log()` 与 `from_persistence()`，统一复用现有 event rehydration + projection 能力。
- 提供 `from_persisted_project()`，可从 project snapshot + 独立 event persistence 构建诊断 projection。
- project snapshot 仅负责存在性 / 合法性验证，不反向覆盖 event-derived projection。
- 查询能力覆盖 project/task lifecycle、last event、retry、error、review status。
- `as_dict()` 返回 detached diagnostic representation，禁止暴露 mutable TaskManager、EventLog internals 或 persistence internals。
- 明确 empty event stream 的 legacy compatibility：返回 `unknown` projection。
- missing project、identity mismatch、corrupt event 保持 fail-fast。
- query / projection 不产生 filesystem 写入，且与原始 runtime / persistence 对象隔离。
- 新增 `tests/test_workflow_event_query_integration.py`，覆盖 persisted → rehydrate → query、empty/missing stream、identity mismatch、corrupt event、object isolation、no-write side effect。

### <span style="color:green">√</span> 7.6.10 用户最终验收
```text
pytest tests/test_workflow_event_query_integration.py tests/test_workflow_event_projection_contract.py tests/test_workflow_event_persistence_query_contract.py tests/test_workflow_event_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py tests/test_project_workflow_event_recovery_contract.py -q
46 passed in 1.17s

pytest -q
840 passed in 3.05s
```

7.6.10 Workflow event projection integration / operational query boundary 正式验收完成。

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

**当前节点：7.6.11 Workflow event query contract hardening / compatibility matrix。**

7.6.10 已完成并通过用户专项及全量验收。下一节点继续围绕现有 event query / projection 能力做契约硬化，不进入 event-driven execution 或消息系统。

## 7.6.11 详细计划

1. **Query contract stabilization**
   - 固化 `WorkflowEventQueryService` 的输入校验、返回值和异常边界。
   - 明确 project-level 与 task-level 查询在无事件、未知 task、无 review、无 retry 情况下的行为。
   - 保持所有查询 read-only，不允许隐式改变 projection 或 runtime state。

2. **Compatibility matrix**
   - 覆盖 legacy empty event stream。
   - 覆盖仅有部分 lifecycle event 的历史 stream。
   - 覆盖 unknown event type 与未来扩展 event type。
   - 覆盖 retry / failure / revision / approval 多轮事件组合。
   - 明确 known malformed event 的 fail-fast contract。

3. **Persistence / rehydration parity**
   - 验证 `from_log()` 与 `from_persistence()` 对同一事件集合产生完全一致的 projection / query 结果。
   - 验证不同文件写入顺序不会改变 query 结果。
   - 验证独立 event persistence recovery 后仍保持 deterministic ordering。

4. **Isolation / immutability**
   - 验证 `WorkflowEventQueryService` 不暴露 EventLog 内部容器、TaskManager 或 persistence adapter。
   - 修改 `as_dict()` 返回值不得污染后续查询。
   - 修改原始 EventLog / persistence 返回对象不得污染已经构造的 query service projection。

5. **测试**
   - 新增 `tests/test_workflow_event_query_contract.py` 或等价 contract test。
   - 保持 7.6.1–7.6.10 全部测试无回归。
   - 专项测试覆盖 query API、compatibility matrix、rehydration parity、immutability / isolation。

6. **明确不做**
   - 不实现 event-driven execution。
   - 不实现自动恢复执行。
   - 不引入消息队列、远程 event store、compaction、archive、stream processor。
   - 不改变 TaskManager / ProjectResult 状态机。
   - 不改变 WorkflowEvent ordering / identity / conflict semantics。
   - 不扩展为写操作 API；7.6.11 仍保持纯 read-only observability boundary。

7. **验收流程**
   - AI 在当前唯一开发分支直接编码。
   - 完成后通知用户 Pull。
   - 用户先专项测试，再 `pytest -q`。
   - 测试失败只修复 7.6.11，不推进 7.6.12。
   - 用户确认全量通过后，再更新 DevPlan 并记录测试结果和最终 commit SHA。

---

# DevPlan 变更记录

## 2026-08-22 — 协作与分支纪律
- 固定唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`。
- 固定“规划 → GitHub 编码 → 用户 Pull → 专项测试 → 全量测试 → 用户验收 → DevPlan 更新 → 下一节点”闭环。
- 测试失败时只针对实际错误在当前分支修复，不推进下一功能点。

## 2026-08-22 — 7.5.5 / 7.5.6 验收
- 7.5.5：用户确认 `784 passed in 2.22s`。
- 7.5.6：用户确认 `788 passed in 2.26s`。

## 2026-08-22 — 7.6.1–7.6.4 验收
- 用户确认全量 `807 passed in 2.35s`。
- WorkflowEvent、in-memory log、filesystem persistence、Workflow / Orchestrator lifecycle integration 正式完成。

## 2026-08-22 — 7.6.5 验收
- 用户确认全量 `813 passed in 2.42s`。
- filesystem global / project / task ordered query 与 in-memory ordering parity 正式完成。

## 2026-08-22 — 7.6.6 验收
- `WorkflowEventPersistenceAdapter.load_log()` 完成独立 event log rehydration。
- 用户确认专项 `10 passed in 0.16s`。

## 2026-08-22 — 7.6.7 验收
- `ProjectOrchestrator.resume_persisted()` 支持独立 event persistence recovery。
- 用户确认专项 `32 passed in 0.95s`、全量 `820 passed in 2.59s`。

## 2026-08-22 — 7.6.8 验收
- runtime durable event sink 与 ProjectOrchestrator runtime event persistence 完成。
- 用户确认专项 `38 passed in 1.01s`、全量 `826 passed in 2.80s`。
- 最终实现 commit：`4dec49cbb91bccf24eafead1d262a009aade2bbc`。

## 2026-08-22 — 7.6.9 验收
- 新增 deterministic, read-only workflow event state projection。
- 用户确认专项 `40 passed in 1.06s`。
- 用户确认全量 `834 passed in 2.91s`。
- 7.6.9 Workflow event replay / state projection 正式完成。
- 当前进入 7.6.10 Workflow event projection integration / operational query boundary。

## 2026-08-22 — 7.6.10 验收
- 新增 `runtime/workflow_event_query.py`，完成 persisted project + independent event persistence 的 operational query boundary。
- 新增 `tests/test_workflow_event_query_integration.py`。
- 用户确认专项 `46 passed in 1.17s`。
- 用户确认全量 `840 passed in 3.05s`。
- 实现 commits：`cc96e28`、`4940366`。
- 7.6.10 Workflow event projection integration / operational query boundary 正式完成。
- 当前进入 7.6.11 Workflow event query contract hardening / compatibility matrix。
