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

Phase 7.1 / 7.1.1 / 7.2 / 7.3 / 7.4 / 7.4.1 / 7.4.2 / 7.4.3 / 7.5.1 / 7.5.2 / 7.5.3 / 7.5.4 / 7.5.5 / 7.5.6 已完成。

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

## 设计边界
1. 先定义 provider-independent 的 immutable `WorkflowEvent` value object，不直接绑定数据库。
2. 每个事件具备稳定 event identity、project/task scope、事件类型、发生时间及可序列化 payload。
3. 同一 project/task scope 内必须具有确定排序语义，不依赖文件系统遍历顺序。
4. 明确 event-id 重复、冲突、幂等语义，并与 7.5.5 的 execution-id identity 原则保持一致但不混淆两种身份。
5. Workflow event log 与 project snapshot 分离：snapshot 表示当前状态，event log 表示状态演进历史。
6. 第一阶段只建立 contract + filesystem adapter + Workflow integration boundary；不引入数据库、消息队列或外部 telemetry 平台。
7. 事件写入失败不得静默伪造成功状态；具体 failure policy 在 integration contract 中明确。
8. 不对现有 persistence、history、workflow 核心做无关重构。

## 实施顺序
1. 盘点当前 Workflow / Orchestrator 状态转换入口，确定最小事件集合。
2. 新增 `WorkflowEvent` immutable value object 与 schema/serialization contract。
3. 新增 `WorkflowEventLog` in-memory contract，定义 append / append-if-absent / conflict / ordered query 语义。
4. 新增 `WorkflowEventPersistenceAdapter` filesystem 实现，保证单事件原子写入及读取校验。
5. 增加 duplicate / conflict / ordering / corruption / failure-injection contract tests。
6. 将最小事件集接入 `TaskWorkflow` / `ProjectOrchestrator`，优先覆盖 task state transition、retry、resume 等关键生命周期节点。
7. 运行专项测试。
8. 专项测试通过后运行全量 `pytest -q`。
9. 用户验收后更新 DevPlan，记录测试数量、耗时及最终 commit SHA。

## 建议最小事件类型
- `task.created`
- `task.ready`
- `task.running`
- `task.completed`
- `task.failed`
- `task.blocked`
- `task.retrying`
- `task.resumed`
- `project.resumed`

实际事件集合以当前 Workflow 状态转换代码为准；若需要修改该集合或本节点边界，先向用户说明并获得确认。

## 初步涉及文件
- `runtime/` 下新增 Workflow event model / history / persistence adapter
- 当前实际存在的 `TaskWorkflow` / `ProjectOrchestrator` 实现文件
- `tests/` 下 Workflow event contract / persistence / integration tests
- `DevPlan.md`

## 完成判定
- Workflow event contract 独立于具体存储实现；
- event identity、重复、冲突、排序语义有测试覆盖；
- filesystem persistence 具备原子写入及 corruption boundary；
- 最小生命周期事件能够从 Workflow / Orchestrator 产生；
- 7.5.x persistence / execution-history contract 无回归；
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

**当前节点：7.6 Workflow event log。**

下一轮按固定流程：
1. 读取当前 GitHub 分支实际 Workflow / Orchestrator 代码和现有测试；
2. 明确 7.6 本轮实际修改范围与专项测试计划；
3. 用户已经明确要求继续推进，因此直接在当前唯一开发分支编码；
4. 完成后通知用户 Pull；
5. 用户先运行专项测试，再运行全量 `pytest -q`；
6. 若失败，在同一分支根据实际错误修复，不创建新分支；
7. 用户确认全量通过后更新 DevPlan 并记录最终 SHA；
8. 再制定下一节点计划。

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
