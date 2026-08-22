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

7.1、7.1.1、7.2、7.3、7.4、7.4.1、7.4.2、7.4.3、7.5.1–7.5.6、7.6.1–7.6.11 已完成。

## 7.5 Tool execution logs

### <span style="color:green">√</span> 7.5.1 Tool log ownership / persistence contract
### <span style="color:green">√</span> 7.5.2 Project recovery tool-log integration
### <span style="color:green">√</span> 7.5.3 Audit / query observability boundary
### <span style="color:green">√</span> 7.5.4 Cross-boundary Audit Consistency
### <span style="color:green">√</span> 7.5.5 Execution-history dedup / conflict semantics
### <span style="color:green">√</span> 7.5.6 Persistence atomic batch semantics

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
### <span style="color:green">√</span> 7.6.11 Workflow event query contract hardening / compatibility matrix

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

### <span style="color:green">√</span> 7.6.9 用户最终验收
```text
专项：40 passed in 1.06s
全量：834 passed in 2.91s
```

### 7.6.10 实现结果
- 新增 `runtime/workflow_event_query.py`，建立 read-only operational query boundary。
- 提供 `WorkflowEventQueryService.from_log()`、`from_persistence()` 与 `from_persisted_project()`。
- project snapshot 仅负责存在性 / 合法性验证，不反向覆盖 event-derived projection。
- 查询覆盖 project/task lifecycle、last event、retry、error、review status。
- `as_dict()` 返回 detached diagnostic representation，不暴露 mutable runtime / persistence internals。
- empty event stream 保持 legacy compatibility；missing project、identity mismatch、corrupt event fail-fast。
- query / projection 不产生 filesystem 写入，并与原始 runtime / persistence 对象隔离。

### <span style="color:green">√</span> 7.6.10 用户最终验收
```text
专项：46 passed in 1.17s
全量：840 passed in 3.05s
```

### 7.6.11 实现结果
- 固化 `WorkflowEventQueryService` 输入校验、返回值和异常边界。
- 建立 compatibility matrix：legacy empty stream、partial lifecycle、unknown future event、retry/failure/revision/approval、多轮生命周期及 malformed known event。
- 验证 `from_log()` 与 `from_persistence()` 的 projection/query parity。
- 验证乱序持久化文件仍保持 deterministic ordering。
- 验证 query service、`as_dict()` 与原始 EventLog / persistence 对象之间的 isolation / immutability。
- 保持 query / projection 纯 read-only，不改变 TaskManager、ProjectResult、WorkflowEvent ordering / identity / conflict semantics。
- 新增 `tests/test_workflow_event_query_contract.py` 覆盖上述契约矩阵。

### <span style="color:green">√</span> 7.6.11 用户最终验收
```text
pytest tests/test_workflow_event_query_contract.py tests/test_workflow_event_query_integration.py tests/test_workflow_event_projection_contract.py tests/test_workflow_event_persistence_query_contract.py tests/test_workflow_event_contract.py tests/test_workflow_event_persistence_contract.py tests/test_workflow_event_integration.py tests/test_workflow_event_orchestrator_integration.py tests/test_project_workflow_event_recovery_contract.py -q
56 passed in 1.13s

pytest -q
850 passed in 2.74s
```

7.6.11 Workflow event query contract hardening / compatibility matrix 正式验收完成。

---

# Phase 8 — Production Hardening

## <span style="color:green">√</span> 8.1 Cross-boundary Contract Tests
## ☐ 8.2 Failure Injection Tests
## ☐ 8.3 Security Tests
## ☐ 8.4 LLM Mock Integration Tests
## ☐ 8.5 Long-running Workflow Tests
## ☐ 8.6 Performance / Concurrency Tests
## ☐ 8.7 Documentation / Examples

### 8.1 实现结果
- 新增 `tests/test_workflow_event_end_to_end_contract.py`。
- 覆盖 ProjectPersistence、独立 WorkflowEventPersistence、EventLog rehydration、Projection、QueryService 的完整跨边界链路。
- 验证内存事件流、持久化事件流、project snapshot recovery 三种查询结果保持语义一致。
- 覆盖 retry / failure / revision / approval 生命周期组合及 query snapshot isolation。
- 覆盖乱序持久化后的 deterministic ordering 与 read-only side-effect boundary。
- 用户随后完成代码兼容性修复并确认专项与全量测试均通过。

### <span style="color:green">√</span> 8.1 用户最终验收
```text
专项：tests/test_workflow_event_end_to_end_contract.py —— 用户确认通过
全量：pytest -q —— 用户确认通过
```

8.1 Cross-boundary Contract Tests 正式完成，进入 Failure Injection Tests。

---

# 当前下一动作

**当前节点：8.2 Failure Injection Tests。**

8.1 已建立 Project → Workflow → EventLog → Persistence → Projection → Query 的端到端语义契约。下一步不改变现有业务状态机，而是验证持久化边界在故障注入下不会产生“内存成功但磁盘失败”“部分写入”“错误状态伪成功”等不一致状态。

## 8.2 详细计划

1. **Workflow event durable sink failure**
   - 注入 `save_if_absent()` 持久化失败。
   - 验证 event 不进入 in-memory log。
   - 验证异常向调用方传播，不伪造成功生命周期。

2. **Workflow event batch atomicity**
   - 注入 staged write / `os.replace()` 中途失败。
   - 验证新事件不会留下 partial committed set。
   - 验证已有事件不被破坏，临时文件被清理。

3. **Project snapshot atomicity**
   - 注入 project `save/update/checkpoint` 的 atomic replace 失败。
   - 验证已有 snapshot 保持原内容。
   - 验证失败后不存在残留 temporary snapshot。

4. **Cross-boundary failure invariants**
   - event persistence failure 不得让 WorkflowEventLog 暴露未持久化事件。
   - project persistence failure 不得让旧 snapshot 被新状态覆盖。
   - failure 后恢复读取仍应得到最后一个成功 checkpoint。

5. **测试实现**
   - 新增 `tests/test_failure_injection_contract.py`。
   - 使用 pytest monkeypatch 注入 filesystem failure，不改变生产 API。
   - 优先验证 observable state、filesystem contents、异常传播与 recovery parity。

6. **明确不做**
   - 不改变 WorkflowEvent identity、ordering、conflict semantics。
   - 不改变 TaskManager / ProjectResult 状态机。
   - 不引入 retry policy、自动补偿或新的 durability protocol。
   - 不提前进入 8.3 Security Tests。

7. **验收流程**
   - AI 在当前唯一开发分支直接编码。
   - 用户 Pull 后先运行 8.2 专项测试，再运行 `pytest -q`。
   - 测试失败只修复 8.2，不推进 8.3。
   - 用户确认全量通过后，再更新 DevPlan 并记录最终 commit SHA。

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

## 2026-08-22 — 7.6.10 验收
- 新增 `runtime/workflow_event_query.py`，完成 persisted project + independent event persistence 的 operational query boundary。
- 新增 `tests/test_workflow_event_query_integration.py`。
- 用户确认专项 `46 passed in 1.17s`。
- 用户确认全量 `840 passed in 3.05s`。

## 2026-08-22 — 7.6.11 验收
- 完成 Workflow event query contract hardening / compatibility matrix。
- 新增 `tests/test_workflow_event_query_contract.py`。
- 用户确认专项 `56 passed in 1.13s`。
- 用户确认全量 `850 passed in 2.74s`。
- 7.6.11 正式完成，Phase 8 Production Hardening 进入 8.1 Cross-boundary Contract Tests。

## 2026-08-22 — 8.1 验收
- 新增 `tests/test_workflow_event_end_to_end_contract.py`，完成跨 Project → Workflow → EventLog → Persistence → Projection → Query 的端到端契约覆盖。
- 用户确认该专项测试通过，并确认全量 `pytest -q` 通过。
- 8.1 正式完成，当前进入 8.2 Failure Injection Tests。

## 2026-08-22 — 8.2 启动
- 新增 `tests/test_failure_injection_contract.py`，开始验证 workflow event durable sink、event batch atomicity、project snapshot atomicity 与 recovery boundary。
- 当前等待用户专项测试与全量测试验收。
