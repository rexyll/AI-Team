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

### √ 8.7.3 Persistence / Recovery and Event Query / Audit example

已完成 `examples/persistence_recovery.py` 并验收，单文件覆盖完整持久化叙事：
- canonical Task 内嵌 tool execution history（与生产 Developer 流一致）
- 原子项目快照保存 + canonical lifecycle 事件流持久化（事件携带投影层要求的 status payload 契约）
- 模拟进程重启：重启边界之后全部使用全新 adapter 实例，仅从磁盘恢复
- 恢复等价校验：task statuses 与 ProjectResult 语义一致
- 跨存储恢复查询：`WorkflowEventQueryService.from_persisted_project()`
- 只读审计：`ToolExecutionAudit.records()/summary()` 过滤查询与 `audit_consistency()` 双链路一致性报告

同节点修复（经用户确认）：四个 `examples/*.py` 补齐仓库根路径自举，使 README 声称的独立运行方式真实可用；顺带确认 `tools/registry.py` 仅兼容 Python≥3.14（类级 `def list` 遮蔽 + 急切注解求值），与官方环境承诺一致。

遗留记录（转入 8.7.4 production configuration checklist）：`config/model.py` 导入即急切实例化 OpenAI 客户端并强制要求 `AGNES_API_KEY`；openai、python-dotenv 为未声明依赖。

专项测试：`tests/test_persistence_recovery_example_contract.py`。
最终 commit：`7cb8b96`。

验收状态：**用户已确认专项及全量测试通过。**

### √ 8.7.4 Production Configuration Checklist

已完成生产配置清单并验收：
- `requirements.txt` 精确锁定 `openai==3.1.0`、`python-dotenv==1.2.3`（版本取自本地 .venv 实测）
- 新增 `docs/production_configuration.md`：Python 3.14 硬性依据（tools/registry.py PEP 649 依赖）、环境变量表与导入期急切实例化警告、MockLLM 无网络模式、workspace sandbox 默认值与覆盖方式、持久化原子重命名存储要求、只读操作契约、部署前验证命令
- `setup.md` §1/§3 修正为真实依赖契约陈述
- 契约测试含跨文件一致性检查：`config/model.py` 第三方导入必须全部在 requirements.txt 锁定

处理深度（经用户确认）：文档化 + 声明依赖；不改运行时代码；惰性化重构留待 Phase 8 后独立评估。

专项测试：`tests/test_production_configuration_contract.py`。
最终 commit：`49f5c62`。

验收状态：**用户已确认专项及全量测试通过。**

### 8.7.5 DeveloperAgent LLM 注入修复 & Release Readiness & Final End-to-End Smoke Test

Phase 8 收官节点（经用户确认采用"先修缺陷再冒烟"路线）。

A. LLM 注入与事件持久化缺陷修复——专项验证发现的三个真实缺陷：
- 缺陷①：`DeveloperAgent.run()` 绕过注入的 `self.llm` 直接调用模块级 provider client
- 缺陷②：`PlannerAgent`（经 `create_plan`→`ask_ai`）同样绕过注入契约
- 缺陷③：`ProjectOrchestrator.execute()` 装配内部 Orchestrator 时只补挂 `_workflow_event_log` 未重建 `_workflow_event_sink`，TaskWorkflow 全部生命周期事件（developer_completed/tester/review/approved）被静默丢弃、不落盘——主入口运行真实项目时恢复审计链断裂

修复落地：
- `runtime/llm/base.py`：新增提供者中立的 `LLMToolCall` / `LLMResponse` 契约与 `generate_with_tools()` 默认降级实现（仅实现 generate() 的自定义子类零改动兼容）
- `runtime/llm/provider.py`：ProviderLLM 实现原生工具调用到中立契约的映射
- `runtime/llm/mock.py`：MockLLM 支持脚本化工具调用轮次（`tool_script`），既有构造签名向后兼容；脚本耗尽后降级为固定终答防止死循环
- `agents/developer.py`：工具循环改走 `self.llm.generate_with_tools()`，移除对 `config.model` 全局 client 的依赖
- `agents/planner.py`：`create_plan` 增加可选 `llm` 参数（默认 None 走旧路径，既有 monkeypatch 测试零破坏），`PlannerAgent.run` 改走 `self.llm`
- `core/orchestrator.py`：新增公开 `set_workflow_event_log()`，统一重建 log 与 sink
- `core/project_orchestrator.py`：`execute()` 改走该 setter，工作流级事件恢复正常持久化

B. 发布就绪交付：
- `docs/release_readiness.md`：逐项链接验收证据的发布门禁清单（含已接受的限制项）
- `tests/test_developer_llm_injection_contract.py`：注入边界回归守卫（脚本化工具调用驱动真实工具在沙盒工作区执行、纯文本降级、脚本耗尽终答、非法脚本拒绝）
- `tests/test_release_documentation_contract.py`：四份发布文档完备性与交叉引用
- `tests/test_release_readiness_smoke_contract.py`：真 Planner/Architect/Developer/Tester/Reviewer + MockLLM 注入，零网络贯穿 用户需求 → 编排执行 → 事件持久化 → 重启恢复 → 跨存储查询 → 真实工具历史审计

专项测试：`tests/test_developer_llm_injection_contract.py`、`tests/test_release_documentation_contract.py`、`tests/test_release_readiness_smoke_contract.py`。
最终 commit：`9c3c026`。

验收状态：**用户已确认专项及全量测试通过（931 passed, 0 warnings）。**

迭代记录：
- 首轮全量暴露 llm_base 签名注解契约回归（新增代码引入 future import 所致，已移除恢复急切注解）
- 性能契约 [512] 出现单次瞬时失败；沙盒 16 轮同参数压测（含并行与高频线程切换）零复现，总事件数始终精确 2560，判定为环境时序偶发，复跑全绿

**8.7 当前状态：全部节点验收通过。Phase 8（Production Hardening）整体收官。**

---

# 六、Phase 8 收官评估与后续候选方向

## 收官评估

Phase 0–8 全部节点验收完成，生产化目标逐项达成：

- Agent / LLM 可替换：构造器注入贯穿全部五类 agent（本轮修复了 Developer/Planner 两处绕过注入的契约破坏）
- 工具受权限控制、工作区受 sandbox 限制：deny-by-default + 路径逃逸防护有安全契约守卫
- 运行状态可持久化、事件可恢复/投影/查询：跨存储恢复等价性与只读审计有端到端冒烟门禁
- 失败边界可验证：故障注入、竞争矩阵、性能回归基线齐备
- 文档与示例：setup、production configuration、release readiness、五个可独立运行示例

发布就绪检查单：`docs/release_readiness.md`。

## 遗留技术债（按优先级，均已有契约测试或文档记录在案）

1. `config/model.py` 惰性初始化重构：消除导入即建 OpenAI client 的副作用与 `AGNES_API_KEY` 强制前置
2. `main.py` 的 `run_project` 返回类型与 `ProjectOrchestrator.run()` 实际返回的 `ProjectResult` 不匹配（CLI 展示层遗留问题）
3. architect/tester/reviewer 中未使用的 `ask_ai` 导入清理
4. 性能契约 [512] 环境时序偶发：已复跑全绿并留档，后续若再现按 8.7.5 迭代记录的取证协议处理

## 后续方向（待产品决策）

1. **技术债清理节点（Phase 8.8 候选）**：惰性初始化重构 + main.py 返回类型修正 + 死导入清理，一次性收口
2. **版本化发布**：打 tag（如 v0.9.0-rc），以 release_readiness 检查单为门禁走一次正式发布流程
3. **新能力规划（Phase 9 候选）**：在现有生产化基座上扩展新方向，需先明确产品目标再立项
4. **真实 LLM 端到端验证**：用配置好的 provider 跑通一次完整真实项目（当前所有验收均为 mock 注入）
