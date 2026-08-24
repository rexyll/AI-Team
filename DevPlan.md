# AI-Team DevPlan

> 项目仓库：`rexyll/AI-Team`
> 当前唯一开发分支：`main`（2026-08-23 由 refactor/runtime-architecture-7.5.5-execution-history-semantics 迁移而来；旧主线已留档于标签 `backup/legacy-main`）
>
> **项目目的：构建一个可持续运行、可恢复、可审计、可验证的 AI 软件开发团队。** 系统不是简单的多 Agent Demo，而是让 Planner / Architect / Developer / Tester / Reviewer / Orchestrator 形成稳定的软件工程闭环：用户需求 → 计划 → 依赖调度 → Agent 执行 → Tester 质量门禁 → Reviewer 审核/返工 → 项目结果 → 持久化恢复 → 事件审计与查询。
>
> **生产目标：** Agent 可替换、LLM 可替换、工具受权限控制、工作区受 sandbox 限制、运行状态可持久化、事件可恢复/投影/查询、失败边界可验证，并最终具备并发、长运行、性能、安全和文档示例等生产化基础。

## 协作与分支纪律

1. 所有开发、修复、测试和 DevPlan 更新均在当前唯一开发分支进行。
2. 不创建临时分支，不随意切换历史分支，不 merge/cherry-pick 其他分支；如确有必要必须先说明并获得确认。
3. AI 直接在 GitHub 当前开发分支修改代码；用户 Pull 到本地运行专项测试和全量 `pytest -q`。
4. 测试失败时只修复当前节点，不顺手推进下一节点。
5. 用户确认全量测试通过后，记录验收结果和最终 SHA，再进入下一节点。
6. 每个节点均遵循：规划 → GitHub 编码 → Pull → 专项测试 → 全量测试 → 验收 → DevPlan 更新。

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

### 8.7.1 Documentation baseline & setup guide

下一节点首先建立：
- 项目安装与虚拟环境 setup
- 最小运行流程
- 测试运行方式
- Agent / LLM provider 配置入口
- Tool registry / permission / workspace sandbox 配置入口
- persistence / recovery 基本使用说明
- 当前支持的 canonical runtime contract 概览

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

---

# 七、Phase 8.8 技术债清理（发布前维护节点）

## 8.8 惰性初始化与 CLI 修正

- `config/model.py`：移除导入期 `AGNES_API_KEY` 强制校验与急切 OpenAI client 构造；新增 `get_client()`（首次调用时校验并缓存，导入零副作用）
- `runtime/llm/provider.py`：客户端改为惰性解析——构造 ProviderLLM 零副作用，首次 generate/generate_with_tools 时经 `config.get_client()` 解析；model 默认改为 None→AGNES_MODEL 解析
- `main.py`：`run_project` 改走 canonical 三步流程（create_plan/build_task_manager/execute），返回 `(task_manager, result)`；CLI 新增 PROJECT RESULT 摘要输出（修正遗留的返回类型不匹配）
- 死导入清理：architect/tester/reviewer 移除未使用的 `ask_ai` 导入（planner 保留供 legacy 分支与既有 monkeypatch 测试）
- 文档同步：production_configuration.md §3/§4、release_readiness.md §4、setup.md §3 全部更新为惰性语义
- 新增 `tests/test_lazy_provider_initialization_contract.py`：子进程级守卫——无 `AGNES_API_KEY` 时 `import main`、provider 导入、ProviderLLM 构造必须成功；`get_client()` 仅在无钥实际使用时 RuntimeError；客户端缓存语义

专项测试：`tests/test_lazy_provider_initialization_contract.py`、`tests/test_main.py`。
最终 commit：`68b4e3f`。

验收状态：**用户已确认专项及全量测试通过。**

迭代记录：无钥使用守卫首版未考虑开发者 `.env` 经 `load_dotenv()` 灌回密钥的场景，已改为"导入后、首次使用前"显式移除环境变量，精确覆盖契约边界。

---

# 八、版本化发布：v0.9.0-rc

## 发布门禁核验（以 docs/release_readiness.md 检查单为准）

- 全量测试绿、零 warning（HEAD `68b4e3f`）
- 发布冒烟契约与文档完备性契约在套件内全绿
- 四份发布文档齐备且交叉引用
- Phase 0–8 验收台账完整，各节点均含 commit SHA

## 发布物

- 新增 `CHANGELOG.md`：v0.9.0-rc 条目（Added / Fixed / Changed / Known limitations）
- Tag `v0.9.0-rc`：由用户在本地打标并推送

发布验收状态：**已完成。**

- 发布 commit：`051ed7d`
- Tag：`v0.9.0-rc`（已推送至 origin）

### 8.9 真实运行缺陷修复（v0.9.0-rc 首次实战反馈）

首次 Agnes 真实运行暴露三问题，修复方案经用户确认（全面加固）：

1. **Tester 判定解析过脆（主因）**：原实现要求响应以 TEST_PASSED/TEST_FAILED 开头，真实模型的"推理在前、结论在后"或 markdown 加粗输出全部误杀。已改为前缀快速路径 + 全文判定词扫描；失败信号优先（TEST_FAILED 存在即 failed），与 deny-by-default 哲学一致。Reviewer 同款加固（REVISION_REQUIRED 优先）。
2. **Tester 异常透传缺失**：workflow 的 tester 异常分支只记录兜底文案，真实异常被吞。已对齐 reviewer 路径携带异常原文。
3. **user_guide 工作区描述错误**：实际 sandbox 根为仓库外 `AI-Team\projects\`（物理隔离设计），已更正 §4.1/§6.1/§7。

配套：两角色 system prompt 增加首行结论格式要求；新增 `tests/test_quality_gate_parsing_contract.py`（判定解析 ×12 场景 + workflow 异常透传契约）。

专项测试：`tests/test_quality_gate_parsing_contract.py`、`tests/test_tester.py`、`tests/test_tester_reviewer_context.py`。
最终 commit：`0989c12`。

验收状态：**用户已确认专项及全量测试通过（19 passed 专项，全量无失败无 warning；过程中修复新测试文件自身的 TesterAgent PytestCollectionWarning，别名导入）。**

### √ 8.9.1 真实 Provider 端到端验证记录

2026-08-23 使用 Agnes 真实模型执行完整闭环验证（需求：摄氏度↔华氏度转换 CLI 工具）：

**结果：6/6 任务完成，PROJECT RESULT success=True——首个真实模型端到端闭环。**

- Planner 拆解 6 任务（architect×1 / developer×3 / tester×2），依赖链正确调度
- Developer 表现：探索工作区、编写实现与 26 个测试用例（含往返转换与绝对零度边界）、主动运行 pytest 全绿、自主修复自身引入的 ModuleNotFoundError、清理临时验证文件
- **8.9 修复实战验证：Tester 两连过，解析加固零误杀**
- 安全层实战全部正确拦截：工作区外路径逃逸、管道/链式命令、未授权可执行文件（dir/ls/mkdir/new-item/get-childitem）；且模型每次被拒后能换策略合规重试

已识别不完美（留作后续观察项）：

1. 需求遵循偏差：用户指定的输出目录未进入计划；前期产物误入残留包 accounting_db/，末位验证任务才补齐目标目录
2. Tester 定位为证据审查者而非测试执行者（设计使然，使用者须知悉）
3. 效率：60+ 次工具调用中大量消耗在无关残留目录的探索上——再次印证运行前清理 projects\ 的必要性（user_guide §4.1）

验证产物：`projects\demo01\`（temperature.py / test_temperature.py 26 passed / verify_temperature.py）。

### √ 8.9.2 真实运行对比实验（两组，Agnes 实测）

**实验一：残留干扰假设验证** —— 清空 `projects\` 后重跑同一温度转换需求：
- 工具调用 36 次 vs 脏环境 60+ 次（↓约 40%），耗时 3 分 55 秒
- 结论：运行前清理工作区从"建议"升级为**必要操作**（user_guide §4.1 已载）
- 产物落点正确：`projects\workspace\demo01\`

**实验二：依赖链中等需求**（utils → cli → tests 三阶段，stringkit）：
- 6/6 任务完成，耗时 6 分 42 秒，工具调用 64 次
- Planner 拆解四信号全过：阶段顺序正确 / **五角色首次全部登场** / 依赖调度零乱序 / 粒度 6 任务落于理想区间
- 交付物验收：`python -m stringkit.cli --help` 正常，vowels/palindrome/camelcase 三子命令可用；裸脚本直跑因包内相对导入失败（有使用方式前提）

**系统性观察项（后续节点靶点）**：

1. 需求中的路径约束不进计划（两次复现，产物落点偏离指定目录）→ 修复方向：Planner prompt 强化约束落实 + 计划校验
2. 角色语义漂移：tester 被派"编写测试"、reviewer 被派"执行测试与修复"，与两者 system prompt 的职责契约冲突 → 修复方向：Planner 角色→职责映射说明
3. 交付物验收盲区：质量门禁未覆盖"终端用户如何运行产物"的维度（相对导入问题逃过全部 73 个测试与双重审核）

### 8.10 版本化发布 v0.9.1

以 8.9 修复经真实环境验证有效为依据，发布 `v0.9.1`：
- 包含 8.9 质量门禁加固 + 8.9.1 验证记录
- 门禁：全量 pytest 通过（已完成）+ 真实闭环验证（已完成）

发布状态：**待用户打标推送。**

---

# 七、Phase 9 — 真实运行质量提升

## √ 9.1 Planner 约束落实与角色映射强化

针对 8.9.2 的三类系统性观察项，通过 agent system prompt 加固：

1. **planner**：
   - 新增"用户需求中的显式约束必须逐条落实"条款——输出目录/路径/顺序等约束原样写入相关任务 description，首个实现类任务负责建立目录结构，拆解完成后自检核对
   - 新增角色职责边界映射——"编写单元测试"归 developer；tester 只审查证据不写代码不执行命令；reviewer 只判定不修复；附参考拆解模板
2. **developer**：新增交付前可运行性自检——站在最终用户视角确定确切运行命令并实测；使用包内相对导入的入口禁止要求裸脚本直跑；汇报新增"用户运行交付物的确切命令"条目
3. **reviewer**：职责清单新增第 9 条——检查交付物可运行性（启动命令明确且在包结构下真实可行）

配套契约：`tests/test_prompt_guidance_contract.py`（4 项内容契约，钉住关键条款防止后续编辑无声丢失）。

真实效果验证方式（提示词类改动的最终门禁）：重跑 8.9.2 实验二同需求，观察产物是否落进 `workspace/stringkit/`、测试编写是否归还 developer、CLI 是否可直接按汇报命令运行。

专项测试：`tests/test_prompt_guidance_contract.py`。
验收状态：**待用户确认。**

## √ 9.2 README 刷新

- 状态行更新至 v0.9.1（Phase 0–8 收官 + 真实 provider 端到端验证）
- 架构列表更正为实际五角色闭环描述
- 补充 `docs/user_guide.md` 链接（随发布文档网络）

验收状态：**随 9.1 一并验收。**

## 9.3 GBK 控制台日志崩溃修复（真实运行第二轮反馈）

run4 提示词效果验证运行暴露平台级缺陷：输出重定向（管道/Tee/CI）时 Python 回落系统区域编码（中文 Windows = GBK），agent 进度打印一旦包含非 GBK 字符（如 ñ）即 UnicodeEncodeError，直接杀死整个任务（本次 TASK-004 因此失败）。

修复：`main.py` 新增 `_ensure_log_safe_streams()` 护栏——CLI 入口将 stdout/stderr `reconfigure(errors="replace")`，不可编码字符降级替换而非致命；对无 `reconfigure` 能力的捕获流（如测试框架）安全跳过。文件读写工具已确认原生 UTF-8，无需改动。

配套契约：`tests/test_console_logging_contract.py`（源码接线检查 + 双流功能注入 + 无 reconfigure 容错）。

**9.1 提示词强化真实验证记分卡**：

| 观察项 | 结果 | 证据 |
|---|---|---|
| 角色语义漂移 | ✅ **修复生效** | "编写 pytest 单元测试"分配给 developer；tester 任务为"测试证据审查"；reviewer 任务为"最终项目审核"——完全符合新边界 |
| 可运行性自检 | ✅ 生效迹象明确 | developer 对 CLI 以空串、边界输入等做了十余次实测后才汇报完成 |
| 路径约束落实 | ❌ 未生效 | 产物仍落在 `projects\stringkit\` 而非 `workspace/stringkit/`——仅靠 prompt 条款不足，需升级到计划校验层规则（列入 9.4 候选）|

专项测试：`tests/test_console_logging_contract.py`。
最终 commit：`67479c6`。

验收状态：**用户已确认专项及全量测试通过。真实运行复验（stringkit 第三轮）已完成，见 9.3.1。**

### √ 9.3.1 第三轮真实运行验证记分（GBK 修复后）

stringkit 同需求第三轮：7/7 任务完成，success=True，耗时 19 分 30 秒，工具调用 89 次。

**9.1 提示词强化三信号终判：**

| 观察项 | 终判 | 本轮实证 |
|---|---|---|
| 角色语义漂移 | ✅ **两轮稳定，正式关闭** | 测试编写归 developer（T4/T5）；tester="审查测试证据并给出判定"；reviewer="最终审核并交付" |
| 可运行性自检 | ✅ 关闭 | developer 以 `python -m stringkit.cli` 实测全部三个子命令；CLI 测试覆盖空串/未知命令/--help 边界共 50 用例 |
| 路径约束落实 | ❌ **第三次复现** | 全部产物仍落在 `projects\stringkit\`；prompt 手段确认无效，正式立项 9.4 校验层方案 |

**本轮亮点（真实模型能力证据）：**

- Developer 在 hELLO 断言失败后，未盲目改代码——编写正则追踪脚本逐步分析 split 行为，判定为测试期望错误而非实现缺陷，随后修正测试并补充 10 个边界用例（85 个用例全绿）
- 发现 Panama 句元音数断言错误（11→10）时同样先写验证脚本核实再改
- 两次自主清理临时调试脚本
- CLI 测试新增未知子命令、缺参数等健壮性场景

遗留小瑕疵：`stringkit/tests/test_results.txt` 未清理。

**9.4 候选（待规划）：路径约束计划校验层**
针对三轮复现的"需求路径约束不进计划"，放弃继续调 prompt，改用**确定性后处理**：

1. **新增 `runtime/plan_constraints.py`**（纯函数、零依赖、可独立单测）：
   - `extract_required_paths(requirement)`：从需求原文提取目录型路径 token（排除文件型 spec、URL、无斜杠单词、畸形双斜杠）
   - `apply_path_constraints(plan, dirs)`：缺失的目录约束以【用户约束】行注入**全部**任务描述（含 architect/reviewer，保持全链路可见），幂等可重入
2. **planner 接线**：`create_plan` 解析成功后调用 `_enforce_requirement_paths`，注入时打印透明日志
3. **契约测试**：`tests/test_plan_constraint_injection_contract.py`（提取语义 ×5、注入与幂等 ×4、参数防御 ×2、真实需求回归）

设计取舍：不采用"校验失败打回重试"方案——机械注入保证 100% 落实且不消耗额外模型调用；prompt 条款保留作为第一道防线。

开发过程中修复自检发现的正则边界缺陷：单段目录+尾斜杠（如 `src/`）因段量词 `+` 无法匹配，调整为 `*` 并增加双斜杠过滤。沙盒 14 组断言全过，含实验二真实需求文本回归。

**v2 修订（run5 真实验收暴露设计缺陷）**：v1 的存在性检查是计划级的——只要任意一个任务描述提到过路径即整体跳过注入。run5 中模型恰好把约束句子抄进了单个任务描述，导致其余任务全部漏防、产物再次落错位置。v2 改为**逐任务检查与注入**：每个任务独立判断、独立补齐；planner 日志改为双向可观测（注入时与"模型已自行落实"时都打印）。新增回归契约 `test_plan_wide_mention_does_not_cover_other_tasks` 固化该语义。

专项测试：`tests/test_plan_constraint_injection_contract.py`。
最终 commit：`a5f8fa9`（v1）＋逐任务修订待提交。

验收状态：**专项及全量测试已过、代码已入库；真实验收进行中——第四次运行 stringkit 需求，产物必须落在 `projects\workspace\stringkit\` 且日志出现注入标记。**

## √ 9.4 路径约束计划校验层

针对三次复现的“需求路径约束不进计划”，放弃继续调 prompt，改用确定性后处理：

1. **新增 `runtime/plan_constraints.py`**（纯函数、零依赖、可独立单测）：
   - `extract_required_paths(requirement)`：从需求原文提取目录型路径 token（排除文件型 spec、URL、无斜杠单词、畸形双斜杠）
   - `apply_path_constraints(plan, dirs)`：逐任务检查并注入【用户约束】行，幂等可重入
2. **planner 接线**：`create_plan` 解析成功后调用 `_enforce_requirement_paths`，注入时打印透明日志
3. **契约测试** `tests/test_plan_constraint_injection_contract.py` ×11，含 run5 “计划级提及不等于覆盖”回归

v1→v2 修订：v1 的存在性检查是计划级的（run5 失败根因），v2 改为逐任务检查与注入，见 9.4.1。

专项测试：`tests/test_plan_constraint_injection_contract.py`。
最终 commit：`a5f8fa9`（v1）；v2 修订随门禁可观测性提交入库。

验收状态：**用户已确认测试通过；真实落点验收升级至 9.8 结构化重定向方案解决。**

## √ 9.5 门禁可观测性与终态修复

run6 暴露：tester 未通过路径是裸 `continue`，无耗尽保护且零控制台输出；TASK-002 因此卡死 running，项目 1/8 提前终止。

修复（runtime/workflow.py）：
- 每轮每阶段打印 `[Gate] 任务 轮次/上限: 阶段=判定`
- tester 未通过路径新增耗尽兜底：轮次耗尽后 `record_error + mark_failed + task_failed 事件`，错误信息携带最后门禁状态（run6 回归契约 test_workflow_gate_visibility_contract.py::test_tester_rejection_rounds_terminate_explicitly）
- reviewer 返工分支同步记录轮次来源

配套契约：`tests/test_workflow_gate_visibility_contract.py` ×3。
最终 commit：随门禁可观测性提交入库。

验收状态：**用户已确认测试通过。**

### √ 9.4.1  门禁轨迹首战记分（run7，含 v2 逐任务语义实战）

run7 因 Agnes 免费额度 429 耗尽而中途终止（T003/T004 failed，余者 blocked），但已产出决定性验证数据：

1. **门禁轨迹可观测性 ✅**：`[Gate]` 行完整记录了 TASK-002 三轮判定（tester=failed → passed → passed；reviewer=revision → approved），并驱动真实返工循环走通。run6 的"隐形卡死"之谜就此破案：当时同款三轮循环全程不可见。
2. **v2 逐任务语义实战 ✅**：本轮 Planner 自行将约束写入每个任务描述，日志正确打印"无需注入"分支（双向可观测生效）。
3. **角色映射第四轮稳定 ✅**：测试编写归 developer（T4/T5），tester=证据审查（T7），reviewer=最终审核（T8）。

**路径约束终审定谳**：本轮约束文本已进入全部任务描述（模型自查确认），Developer 也确实"知道"该约束——但产物依然落在 `projects\stringkit\` 且出现 `stringkit\stringkit\` 双层嵌套混乱。至此证明：**提示词、描述注入、模型自查三种文本层手段全部无效**，模型把任务标题中的字面相对路径视为权威。唯一可靠方案是结构化强制（沙盒根目录重定向），立项 9.6。

附带发现：Developer 在真实运行中执行了 `pip install pytest-cov`（宿主机网络可达 pypi）——工具权限策略允许 pip 值得在安全评审中复议。

---


## √ 9.6 多 Provider 按角色模型配置

Phase 4 "LLM 可替换"契约的完整体现：每个角色可独立绑定 (provider, model)，支持 OpenRouter 等任意 OpenAI 兼容端点。

1. **`config/model.py` 多 Profile 化**：`ProviderProfile` 注册表（agnes/openrouter，均可经 `{PREFIX}_BASE_URL/_MODEL` 覆盖）+ `get_client_for(profile)` 每 profile 独立惰性客户端缓存 + `resolve_role_llm_spec(role)` 动态解析 `{ROLE}_PROVIDER/{ROLE}_MODEL` → `DEFAULT_PROVIDER` → profile 默认。解析全部调用时读环境（测试与运行期热切换友好）。旧 `get_client()/ask_ai()` 行为不变。
2. **`ProviderLLM` 增加 `provider_profile` 参数**：显式模型+profile 组合；仅传 model 保持 Agnes 兼容语义；客户端仍惰性解析。
3. **工厂接线**：`create_agent_router` 为五角色各构建绑定 LLM 注入构造器——`{ROLE}_MODEL` 缺省回落 profile 默认。
4. **配置界面即 `.env`**：新增 `.env.example` 模板；切换全模型 = 改 `DEFAULT_PROVIDER` 一行；单点换角色 = 加一行 `{ROLE}_MODEL`。
5. **契约测试** `tests/test_role_model_config_contract.py` ×10：profile 默认值/覆盖/未知拒绝、逐角色绑定与回退、每 profile 客户端缓存隔离、缺凭据惰性报错、工厂注入断言（含 agents 链）。

初始绑定（用户确认）：五角色统一 `stealth/ox-alpha @ openrouter`。

专项测试：`tests/test_role_model_config_contract.py`。
最终 commit：`6acc50d`。

验收状态：**用户已确认专项及全量测试通过（含过时文档契约同步更新）。真实运行验收已完成，见 9.6.1。**

### √ 9.6.1 Ox Alpha 首个完整闭环基线（run8）

五角色全部经 OpenRouter 调用 `stealth/ox-alpha`，**6/6 任务完成，success=True**，耗时 41 分 16 秒。这是项目首个非 Agnes 模型的端到端闭环。

**交付物质量亮点（Ox Alpha 实测能力证据）**：
- utils.py 带 doctest 示例；Developer 编写了纯度检查（输入不被修改断言）、doctest 集成测试、CLI 子进程端到端测试
- 自主调试两处自身缺陷：`MY_VAR_NAME` 用例失败后修正实现（补 `.lower()` 规范化）；测试中 unhashable dict 集合用法报错后改写为迭代比较
- cli.py 实现**双模式导入**（包执行与裸脚本执行均可用），并主动覆盖空参数/未知子命令等健壮性场景
- 最终交付 58+23 个用例全绿，CLI 三子命令实测可用

**基础设施实战验证：**
- ✅ **429 指数退避护栏首次实弹救场**：日志可见两次 `transient 429; retry N/3 in Xs` 后成功，运行未被上游共享池限流打断
- ✅ `[Gate]` 轨迹全程可见，六任务判定链清晰
- ✅ 角色映射第五轮稳定：architect → developer×3 → tester（证据审查）→ reviewer（终审）
- ✅ 注入标记触发：`已将缺失的路径约束注入任务描述`

**路径约束第四次复现（跨模型确认）**：注入的约束描述 Ox Alpha 同样未转化为文件路径行为，产物仍落在 `projects\stringkit\`。至此 Agnes 与 Ox Alpha 双模型一致证明：文本层手段（prompt/描述注入）对路径约束无效，**9.8 沙盒根目录重定向立项依据充分**。

已知小瑕疵：Developer 生成的测试文件曾位于仓库根 `tests/test_utils.py` 与包内重复（后续任务自行覆盖整合）；产物落点仍需 9.8 结构性解决。

本轮基线数据：耗时 41:16（含多次 429 退避等待），工具调用约 40 次，交付 81 个测试用例全绿。

### √ 9.6.1 瞬态失败指数退避（Ox Alpha 冒烟实战反馈）

首次冒烟即命中 `stealth/ox-alpha` 上游共享池 429（管线本身全通：密钥/slug/请求格式均正确）。为避免全量运行中途被瞬态限流杀死，ProviderLLM 新增重试边界：

- `_post_chat` 统一包装 `generate/generate_with_tools` 的 completions 调用
- 可重试集合 {429, 500, 502, 503, 504}；指数退避 2s→4s→…；尊重数字型 Retry-After 头取较大值
- `LLM_MAX_ATTEMPTS` / `LLM_BACKOFF_SECONDS` 环境变量可调；非可重试错误与预算耗尽立即抛出
- 每次重试打印 `[LLM] profile/model transient NNN; retry i/N in Xs` 透明日志

配套契约：`tests/test_llm_retry_backoff_contract.py` ×5（退避序列/不可重试即败/预算耗尽/Retry-After 尊重/tools 路径共享边界）。

开发中自检修复两处测试自身缺陷：假客户端缺 `.chat` 包装层、退避公式 off-by-one（首轮 1s 而非 2s）。

专项测试：`tests/test_llm_retry_backoff_contract.py`。
验收状态：**沙盒 5/5 通过；随 9.6 一并由用户本地门禁验收。**

## √ 9.7 文档同步（随 9.6）

- `docs/production_configuration.md` §3 重写为多 Provider 表格与角色绑定规则
- `docs/user_guide.md` §3 改为 OpenRouter + Ox Alpha 最小配置指引
- 新增 `.env.example` 入库

验收状态：**随 9.6 一并验收。**

---

## √ 9.8 沙盒根目录重定向（路径约束的结构化终解）

四轮真实运行跨两模型证明文本层手段对路径约束无效。本节点改为**结构化强制**：需求含显式输出目录时，运行前把沙盒根锚定到该目录的父级，使模型的相对路径物理落位正确——模型零配合需求。

1. **`security/workspace.py`**：新增 `set_default_workspace_root()`（运行期热替换默认沙盒）+ `get_default_workspace_root()` + 纯函数 `anchor_workspace_root(base, mandated)`（锚定规则：保留除末段外的完整父链，末段由 agent 写文件时自然生成）
2. **`main.py`**：新增 `--projects-base` 参数；`run_project` 启动前经 `extract_required_paths` 检测需求约束 → 重定向沙盒根并打印透明日志；未含约束的需求回落默认根
3. 逃逸防护在重定向后的根上依然完整生效

配套契约：`tests/test_sandbox_redirection_contract.py` ×10（锚定规则、重定向后相对解析、逃逸防护存活、requirement→anchor→落点全链推演、CLI 接线源码钉扎）。

文档同步：user_guide §4.1/§6.1 更新为自动重定向语义。

专项测试：`tests/test_sandbox_redirection_contract.py`。
最终 commit：（验收后记录）

验收状态：**待用户确认专项及全量测试通过。真实验收方式：第五次运行 stringkit 需求，日志出现 `[Workspace] 沙盒根已重定向` 且产物必须落在 `projects\workspace\stringkit\`。**

## 后续候选（按优先级）

- **429 退避重试**：✅ 已随 9.6.1 落地（LLM_MAX_ATTEMPTS / LLM_BACKOFF_SECONDS 可调）
- **pip 白名单复议**：Developer 已可在沙盒内 pip install 第三方包（run5 实测），安全评审需明确策略
