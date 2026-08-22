# AI-Team DevPlan

> 当前唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`
>
> **分支纪律：除非确有必要，禁止创建新分支、禁止随意切换分支。所有后续开发、修复、测试与 DevPlan 更新均在当前唯一开发分支进行。若确需创建/切换分支，必须先明确说明原因、目标分支、切换命令及返回当前开发分支的方法，并等待用户确认。**
>
> **代码修改边界：AI 直接在 GitHub 当前开发分支修改代码；用户负责 Pull 到本地测试。AI 不要求用户为了单个功能点自行切换分支。**

## 开发协作固定流程（后续所有功能点必须遵守）

### 1. 规划
- 根据本 DevPlan 当前未完成节点确定下一开发任务。
- 开始编码前明确本次功能点的目标、涉及文件、实现边界、专项测试范围。
- 不擅自扩大需求，不擅自改变已经确认的架构边界。

### 2. GitHub 直接开发
- 在当前唯一开发分支 `refactor/runtime-architecture-7.5.5-execution-history-semantics` 上直接编写/修改代码。
- 优先小范围、可审查、可回滚的修改。
- **禁止为了方便而新建临时分支或在历史分支之间来回切换。**
- 如确需分支操作，必须提前向用户说明并获得确认。

### 3. 用户 Pull + 测试
- AI 完成代码后，不代替用户假设本地测试通过。
- 通知用户 Pull 当前分支最新提交，并运行指定专项测试。
- 专项测试通过后，再要求执行全量 `pytest -q`。

### 4. 测试失败处理
- 用户把实际 pytest 错误信息完整发送回来。
- AI 只根据实际错误定位问题，并在**同一个当前开发分支**修复。
- 修复完成后通知用户再次 Pull、再次测试。
- 重复此循环，直到专项测试和全量测试全部通过。
- **测试未通过时不得推进到下一规划节点，也不得借修复之机顺手引入下一阶段功能。**

### 5. 测试通过后的 DevPlan 更新
- 用户发送最终 `pytest` 结果并确认测试通过后，AI 才更新 DevPlan。
- 在对应任务处标记 `√`，记录用户验收的测试数量、耗时和当前最终 commit SHA。
- 不根据 AI 自己的推测标记完成。

### 6. 下一步规划
- 完成一个功能点后，先给出下一节点的详细实施计划：
  - 目标
  - 设计边界
  - 涉及文件
  - 实现步骤
  - 专项测试
  - 全量测试
  - 完成判定标准
- 等待用户发送“继续按计划推进工作”或同义明确指令后，才开始下一节点编码。

### 7. DevPlan 变更
- 如果开发过程中发现 DevPlan 的技术细节、顺序、边界或验收标准需要修改，必须先向用户提出变更原因和建议方案。
- **未经用户确认不得修改已确认的开发规划。**
- 用户确认后，再同步修改 DevPlan，并在修改记录中说明变更原因。

### 8. 分支安全原则
- 当前工作基线固定为：`refactor/runtime-architecture-7.5.5-execution-history-semantics`。
- 当前已存在的其他历史/辅助分支仅作为历史参考，不作为后续开发目标：
  - `main`
  - `refactor/runtime-architecture`
  - `refactor/runtime-architecture-7.5.3-audit-v2`
  - `refactor/runtime-architecture-7.5.4-audit-consistency`
  - 以及其他 `origin/tmp/*`、`origin/docs/*` 分支。
- 后续默认不从这些分支 cherry-pick、merge 或切换，避免重复工作和代码漂移。
- 每次开始新节点前，以用户提供的当前分支、`git status`、`git log` 为事实基线。

---

# 当前状态

**Phase 7 — Persistence / Observability**

最新用户验收基线：

```text
pytest -q
784 passed in 2.22s
```

7.5.5 Execution-history dedup / conflict semantics 已完成并通过用户全量验收。

Phase 3 Context Lifecycle Governance、Phase 4 LLM Abstraction、Phase 5 Tool / Sandbox Architecture、Phase 6 Workflow / Project Orchestrator 均已完成。

Phase 7.1 / 7.1.1 / 7.2 / 7.3 / 7.4 / 7.5.1 / 7.5.2 / 7.5.3 / 7.5.4 / 7.5.5 已完成。

---

# Phase 3 — AgentContext 正式化

## <span style="color:green">√</span> 3.4.6 Legacy dependency bridge isolation

**Phase 3 Context Lifecycle Governance 已完成。**

# Phase 4 — LLM Abstraction

## <span style="color:green">√</span> 4.1 BaseLLM Contract
## <span style="color:green">√</span> 4.2 MockLLM
## <span style="color:green">√</span> 4.3.1 ProviderLLM adapter contract
## <span style="color:green">√</span> 4.3.2 Agent LLM injection
## <span style="color:green">√</span> 4.4 Workflow → LLM-independent
## <span style="color:green">√</span> 4.5 Provider/config 可替换

**Phase 4 已完成。**

# Phase 5 — Tool / Sandbox Architecture

## <span style="color:green">√</span> 5.1 Tool Contract
## <span style="color:green">√</span> 5.2 Tool Registry Contract
## <span style="color:green">√</span> 5.3 Tool Argument Validation
## <span style="color:green">√</span> 5.4 Workspace Sandbox
## <span style="color:green">√</span> 5.5 Tool Permission Policy
## <span style="color:green">√</span> 5.6 Tool Error Contract

**Phase 5 已完成。**

# Phase 6 — Workflow / Project Orchestrator

## <span style="color:green">√</span> 6.1 TaskWorkflow 状态机
### <span style="color:green">√</span> 6.1.1 Stage execution → state transition contract
### <span style="color:green">√</span> 6.1.2 TaskWorkflow → transition contract integration
## <span style="color:green">√</span> 6.2 Dependency-aware Scheduler
### <span style="color:green">√</span> 6.2.1 Dependency Scheduler read-only contract
### <span style="color:green">√</span> 6.2.2 Orchestrator readiness boundary convergence
## <span style="color:green">√</span> 6.3 ProjectOrchestrator
## <span style="color:green">√</span> 6.4 Task 并行执行
### <span style="color:green">√</span> 6.4.1 Task layer executor contract
### <span style="color:green">√</span> 6.4.2 Layer-based Orchestrator integration
### <span style="color:green">√</span> 6.4.3 Concurrency hardening
## <span style="color:green">√</span> 6.5 Retry / Resume
### <span style="color:green">√</span> 6.5.1 Retry lifecycle contract
### <span style="color:green">√</span> 6.5.2 Retry policy integration
### <span style="color:green">√</span> 6.5.3 Resume in-memory execution boundary
### <span style="color:green">√</span> 6.5.4 Retry / Resume integration
## <span style="color:green">√</span> 6.6 ProjectResult

**Phase 6 已完成。**

# Phase 7 — Persistence / Observability

## <span style="color:green">√</span> 7.1 Task persistence contract
## <span style="color:green">√</span> 7.1.1 Task persistence adapter
## <span style="color:green">√</span> 7.2 Project persistence
## <span style="color:green">√</span> 7.3 Agent execution records

## <span style="color:green">√</span> 7.4 Project Resume / Recovery
### <span style="color:green">√</span> 7.4.1 Persisted project resume contract
### <span style="color:green">√</span> 7.4.2 ProjectOrchestrator persisted resume integration
### <span style="color:green">√</span> 7.4.3 Recovery consistency / corruption boundaries

已完成 persisted project → runtime state 恢复边界、Planner-free continuation、TaskManager identity consistency、ProjectResult consistency，以及 corrupt snapshot / identity mismatch / unknown task tool-history 等恢复边界。

## <span style="color:green">√</span> 7.5 Tool execution logs
### <span style="color:green">√</span> 7.5.1 Tool log ownership / persistence contract
### <span style="color:green">√</span> 7.5.2 Project recovery tool-log integration
### <span style="color:green">√</span> 7.5.3 Audit / query observability boundary
### <span style="color:green">√</span> 7.5.4 Cross-boundary Audit Consistency
### <span style="color:green">√</span> 7.5.5 Execution-history dedup / conflict semantics

7.5.5 已完成：统一 `execution_id` identity、幂等重复、conflict 语义，并在 `ToolExecutionHistory`、`ToolExecutionPersistenceAdapter`、project recovery 边界保持一致；batch merge / persistence 在写入前进行冲突检查，不允许故意产生部分更新。

用户最终验收基线：

```text
pytest -q
784 passed in 2.22s
```

当前用户开发基线 commit：`556013c`。

## ☐ 7.5.6 Persistence atomic batch semantics

### 目标
把多项 runtime observability 更新收敛为单一可恢复事务边界，验证失败时不得留下半更新 snapshot。

### 设计边界
1. 明确 project snapshot、task runtime state、ProjectResult、tool execution history 的原子提交边界。
2. 所有 preflight validation 必须发生在实际替换持久化文件之前。
3. 写入失败时必须清理临时文件，并保持旧 snapshot 可恢复。
4. 不引入数据库；继续保持 persistence adapter 与 Workflow 核心层解耦。
5. 不改变 7.5.5 已确认的 execution-id dedup / conflict semantics。

### 实施顺序
1. 检查当前 `ProjectPersistenceAdapter` 的 `save/update/checkpoint` 原子边界。
2. 明确多对象/多文件提交时的 staging、commit、rollback 语义。
3. 增加 failure-injection / partial-write contract tests。
4. 修复实现，使失败路径保持旧 snapshot 不变。
5. 运行专项测试。
6. 专项测试通过后运行全量 `pytest -q`。
7. 用户验收后记录最终 SHA，再标记 7.5.6 完成。

### 涉及文件（初步）
- `runtime/project_persistence.py`
- `runtime/tool_execution_persistence.py`
- `runtime/tool_execution_history.py`（仅在确有必要时修改）
- `tests/` 下对应 persistence atomicity contract tests

### 完成判定
- failure injection 不产生半更新 snapshot；
- 旧 snapshot 在候选状态校验/写入失败后仍可正常 load；
- 成功提交后 snapshot 中各组成部分一致；
- 7.5.5 的 dedup/conflict contract 不回归；
- 全量 `pytest -q` 通过；
- 用户确认测试结果后才能标记 `√`。

## ☐ 7.6 Workflow event log

### Phase 7 开发边界

Phase 7 的目标不是立即引入数据库，而是先建立稳定的 persistence / observability contracts，再选择具体存储实现。

优先顺序：

1. Task persistence schema / serialization contract；
2. Task persistence adapter；
3. Project persistence schema / adapter；
4. Agent execution records / execution history；
5. persisted state 接入 `ProjectOrchestrator.resume()`；
6. Tool / Workflow observability；
7. 具体数据库 / 文件存储实现必须服从上述 contract，不反向污染 Workflow 核心层。

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

**当前节点：7.5.6 Persistence atomic batch semantics。**

按固定协作流程执行：

1. 先读取当前 GitHub 分支的实际代码和测试基线；
2. 明确 7.5.6 本轮修改范围与专项测试计划；
3. 等待用户发送“继续按计划推进工作”后，在当前唯一开发分支直接修改代码；
4. 完成后通知用户 Pull；
5. 用户先运行专项测试，再运行全量 `pytest -q`；
6. 若失败，依据实际错误在同一分支修复，不创建新分支；
7. 用户确认全量通过后，更新本 DevPlan 并记录最终 SHA；
8. 再制定 7.6 的详细计划，等待下一次明确推进指令。

---

# DevPlan 变更记录

## 2026-08-22 — 固化开发协作与分支纪律

- 固定唯一开发分支：`refactor/runtime-architecture-7.5.5-execution-history-semantics`。
- 明确后续原则上不创建/切换分支，避免历史分支与当前工作线交叉导致重复开发。
- 固定“规划 → GitHub 编码 → 用户 Pull → 专项测试 → 全量测试 → 用户验收 → DevPlan 更新 → 下一节点”的闭环。
- 测试失败时只针对实际错误在当前分支修复，不推进下一功能点。
- DevPlan 技术细节需要调整时，先向用户提出并等待确认。
- 用户最近一次全量测试结果：`784 passed in 2.22s`。
