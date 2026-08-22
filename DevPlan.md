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

7.1、7.1.1、7.2、7.3、7.4、7.4.1、7.4.2、7.4.3、7.5.1–7.5.6、7.6.1–7.6.9 已完成。

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

**当前节点：7.6.10 Workflow event projection integration / operational query boundary。**

7.6.9 已完成并通过用户专项及全量验收。下一节点只围绕已有 projection 能力做最小化应用层集成，不进入 event-driven execution 或消息系统。

## 7.6.10 详细计划

1. **Projection 与 persistence / recovery 统一入口**
   - 在不改变 project snapshot schema 的前提下，提供从 persisted project + 独立 event persistence 获取 projection 的最小入口。
   - 复用 `WorkflowEventPersistenceAdapter.load_log()` 与 `WorkflowEventProjector`，禁止复制恢复 / 排序逻辑。

2. **Operational query boundary**
   - 提供 project/task read-only 查询能力：project lifecycle、task lifecycle、last event、retry、error、review status。
   - 不暴露 `_events`、TaskManager mutable object 或 persistence internals。

3. **Recovery consistency**
   - projection 仅用于诊断 / 观察，不反向覆盖 project snapshot。
   - 对缺失 event stream、空 stream、project identity mismatch、corrupt event 定义明确 fail-fast / legacy compatibility contract。

4. **Persistence isolation**
   - 验证 query / projection 不产生任何写入。
   - 验证 projection 与原 EventLog、filesystem event record、TaskManager 完全隔离。

5. **测试**
   - 新增 projection integration contract tests。
   - 覆盖 persisted → rehydrate → project/task query、empty/missing stream、identity mismatch、corrupt event、object isolation、no-write side effect。
   - 保持 7.6.1–7.6.9 无回归。

6. **明确不做**
   - 不实现 event-driven execution。
   - 不实现自动恢复执行。
   - 不引入消息队列、远程 event store、compaction、archive、stream processor。
   - 不改变 TaskManager / ProjectResult 状态机。
   - 不改变 WorkflowEvent ordering / identity / conflict semantics。

7. **验收流程**
   - AI 在当前唯一开发分支直接编码。
   - 完成后通知用户 Pull。
   - 用户先专项测试，再 `pytest -q`。
   - 测试失败只修复 7.6.10，不推进 7.6.11。
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
